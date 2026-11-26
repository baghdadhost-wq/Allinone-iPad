#import <Foundation/Foundation.h>
@interface EmbeddedNode : NSObject
+ (void)start:(NSString *)script state:(NSString *)state bundle:(NSString *)bundle;
@end
