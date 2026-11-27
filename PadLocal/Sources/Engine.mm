#import "Engine.h"
#import <llama/llama.h>
#import <TargetConditionals.h>
#if !TARGET_OS_OSX
#import <os/proc.h>
#endif
#import <sys/sysctl.h>
#import <sys/mman.h>
#import <libkern/OSCacheControl.h>
#import <unistd.h>
#include <atomic>
#include <vector>
#include <memory>
#include <string>
#include <algorithm>
#include <cmath>
#include <cstring>
static std::atomic<bool> stopped(false);
void PLStop(void){stopped.store(true);}
void PLResetStop(void){stopped.store(false);}
uint64_t PLAvailable(void){
#if TARGET_OS_OSX
    return 0; // Command-line verification does not use the iPad memory gauge.
#else
    return os_proc_available_memory();
#endif
}
BOOL PLDebugAttached(void){
    int mib[]={CTL_KERN,KERN_PROC,KERN_PROC_PID,getpid()};
    struct kinfo_proc info={}; size_t n=sizeof(info);
    return sysctl(mib,4,&info,&n,nullptr,0)==0 && (info.kp_proc.p_flag & P_TRACED)!=0;
}
// Specialize a float multiplier for the repetition penalty at runtime. No input code is executed.
class Penalty {
    void *page=MAP_FAILED;
    size_t length=0;
    using Fn=float(*)(float);
    Fn positive=nullptr, negative=nullptr;
public:
    explicit Penalty(bool enable,float factor){
#if defined(__arm64__)
        if(!enable || !PLDebugAttached())return;
        length=(size_t)getpagesize();
        page=mmap(nullptr,length,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);
        if(page==MAP_FAILED)return;
        auto emit=[](uint32_t *out,float value){
            uint32_t bits; memcpy(&bits,&value,4);
            out[0]=0x52800009|((bits&65535)<<5); // movz w9, low
            out[1]=0x72A00009|((bits>>16)<<5);   // movk w9, high, lsl #16
            out[2]=0x1E270121; // fmov s1,w9
            out[3]=0x1E210800; // fmul s0,s0,s1
            out[4]=0xD65F03C0; // ret
        };
        uint32_t *p=(uint32_t*)page; emit(p,1/factor);emit(p+5,factor);
        sys_icache_invalidate(page,40);
        if(mprotect(page,length,PROT_READ|PROT_EXEC)==0){
            positive=(Fn)p;negative=(Fn)(p+5);
        }
#endif
    }
    bool active() const {return positive!=nullptr;}
    float apply(float x,float factor) const {return positive?(x<0?negative(x):positive(x)):(x<0?x*factor:x/factor);}
    ~Penalty(){if(page!=MAP_FAILED)munmap(page,length);}
};
NSString *PLGenerate(NSString *path,NSArray<NSDictionary<NSString *,NSString *> *> *turns,BOOL jit,void (^update)(NSString *),NSString *__autoreleasing *error){
    auto fail=[&](NSString *why)->NSString*{*error=why;return @"";};
    static dispatch_once_t once;dispatch_once(&once,^{llama_backend_init();});
    auto params=llama_model_default_params();params.n_gpu_layers=99;params.load_mode=LLAMA_LOAD_MODE_MMAP;
#if TARGET_OS_OSX
    params.n_gpu_layers=0; // Hosted macOS runners may have no Metal device.
#endif
    params.progress_callback=[](float,void*){return !stopped.load();};
    std::unique_ptr<llama_model,decltype(&llama_model_free)> model(llama_model_load_from_file(path.fileSystemRepresentation,params),llama_model_free);
    if(!model)return fail(stopped?@"تم الإيقاف":@"تعذر تحميل GGUF. تحقق من الذاكرة وتوافق الملف.");
    auto cp=llama_context_default_params();cp.n_ctx=1536;cp.n_batch=128;cp.n_ubatch=128;
    cp.abort_callback=[](void*){return stopped.load();};
    std::unique_ptr<llama_context,decltype(&llama_free)> ctx(llama_init_from_model(model.get(),cp),llama_free);
    if(!ctx)return fail(@"تعذر حجز ذاكرة السياق.");
    const auto *v=llama_model_get_vocab(model.get());
    const char *tmpl=llama_model_chat_template(model.get(),nullptr);
    if(!tmpl)return fail(@"قالب المحادثة مفقود.");
    std::vector<llama_chat_message> msgs;
    for(NSDictionary *m in turns) msgs.push_back({[m[@"role"] UTF8String],[m[@"content"] UTF8String]});
    std::vector<llama_token> tokens;
    for(;;){
        std::string prompt;
        if(strstr(tmpl,"<|turn>") != nullptr){
            for(const auto &m:msgs){
                prompt+="<|turn>";
                prompt+=strcmp(m.role,"assistant")==0 ? "model" : m.role;
                prompt+="\n"; prompt+=m.content; prompt+="<turn|>\n";
            }
            prompt+="<|turn>model\n";
        } else {
            int bytesNeeded=llama_chat_apply_template(tmpl,msgs.data(),msgs.size(),true,nullptr,0);
            if(bytesNeeded<=0 || bytesNeeded>4000000)return fail(@"قالب المحادثة غير مدعوم أو النص طويل جدا.");
            std::vector<char> buffer(bytesNeeded+1);
            int written=llama_chat_apply_template(tmpl,msgs.data(),msgs.size(),true,buffer.data(),buffer.size());
            if(written!=bytesNeeded)return fail(@"تعذر تجهيز قالب المحادثة.");
            prompt.assign(buffer.data(),written);
        }
        const auto sz=(int32_t)prompt.size();
        int nt=-llama_tokenize(v,prompt.data(),sz,nullptr,0,true,true);
        if(nt<=0)return fail(@"تعذر ترميز النص.");
        if(nt<=1280){
            tokens.resize(nt);if(llama_tokenize(v,prompt.data(),sz,tokens.data(),nt,true,true)!=nt)return fail(@"تعذر ترميز المحادثة.");
            break;
        }
        if(msgs.size()<3)return fail(@"الرسالة تتجاوز سياق هذه النسخة. قسمها إلى رسالتين.");
        msgs.erase(msgs.begin(),msgs.begin()+2);
    }
    auto decode=[&](llama_token *p,int n){return llama_decode(ctx.get(),llama_batch_get_one(p,n))==0;};
    for(size_t i=0;i<tokens.size();i+=128){
        if(stopped)return fail(@"تم الإيقاف");if(!decode(tokens.data()+i,(int)std::min<size_t>(128,tokens.size()-i)))return fail(@"تعذرت معالجة الطلب.");
    }
    Penalty penalty(jit,1.10f);
    if(jit && !penalty.active())return fail(@"لم يسمح النظام بتشغيل JIT. أوقف الخيار لتشغيل Metal.");
    std::vector<llama_token> recent;
    auto sampler=std::unique_ptr<llama_sampler,decltype(&llama_sampler_free)>(llama_sampler_chain_init(llama_sampler_chain_default_params()),llama_sampler_free);
    llama_sampler_chain_add(sampler.get(),llama_sampler_init_top_k(40));
    llama_sampler_chain_add(sampler.get(),llama_sampler_init_top_p(.9f,1));
    llama_sampler_chain_add(sampler.get(),llama_sampler_init_temp(.7f));
    llama_sampler_chain_add(sampler.get(),llama_sampler_init_dist(LLAMA_DEFAULT_SEED));
    std::string bytes;NSString *answer=@"";
    for(int i=0;i<256 && !stopped;i++){@autoreleasepool{
        float *logits=llama_get_logits_ith(ctx.get(),-1);
        if(!logits)return fail(@"تعذرت قراءة نتيجة النموذج.");
        auto unique=recent;std::sort(unique.begin(),unique.end());unique.erase(std::unique(unique.begin(),unique.end()),unique.end());
        for(auto t:unique)logits[t]=penalty.apply(logits[t],1.10f);
        auto id=llama_sampler_sample(sampler.get(),ctx.get(),-1);
        if(llama_vocab_is_eog(v,id))break;
        std::vector<char> piece(128);int n=llama_token_to_piece(v,id,piece.data(),piece.size(),0,false);
        if(n<0){piece.resize(-n);n=llama_token_to_piece(v,id,piece.data(),piece.size(),0,false);}
        if(n>0)bytes.append(piece.data(),n);
        NSString *valid=[[NSString alloc] initWithBytes:bytes.data() length:bytes.size() encoding:NSUTF8StringEncoding];
        if(valid){answer=valid;update(answer);}
        recent.push_back(id);if(recent.size()>48)recent.erase(recent.begin());
        if(!decode(&id,1)) {if(stopped)break;return fail(@"توقف المحرك أثناء التوليد.");}
    }}
    return answer;
}
