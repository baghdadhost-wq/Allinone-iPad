#import <Foundation/Foundation.h>
#ifdef __cplusplus
extern "C" {
#endif
uint64_t PLAvailable(void);
BOOL PLDebugAttached(void);
void PLStop(void);
void PLResetStop(void);
NSString * _Nonnull PLGenerate(NSString * _Nonnull path, NSArray<NSDictionary<NSString *,NSString *> *> * _Nonnull turns, BOOL jit, void (^ _Nonnull update)(NSString * _Nonnull), NSString * _Nullable __autoreleasing * _Nonnull error);

#ifdef __cplusplus
}
#endif
