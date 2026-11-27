#import "../Sources/Engine.h"
#include <cstdio>
int main(int argc,char **argv){@autoreleasepool{
    if(argc!=2)return 2;
    PLResetStop();
    NSString *error=nil;
    NSString *answer=PLGenerate([NSString stringWithUTF8String:argv[1]],@[@{@"role":@"user",@"content":@"What is 2 + 2? Answer briefly."}],NO,^(NSString *draft){
        if(draft.length>=28)PLStop();
    },&error);
    if(error || !answer.length){fprintf(stderr,"%s\n",(error ?: @"empty reply").UTF8String);return 1;}
    printf("Local GGUF generation produced %lu characters\n",(unsigned long)answer.length);
    return 0;
}}
