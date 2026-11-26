#import "MobileNode.h"
#import <NodeMobile/NodeMobile.h>
#include <vector>
#include <cstring>

@implementation EmbeddedNode
+ (void)start:(NSString *)script state:(NSString *)state bundle:(NSString *)bundle {
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        NSThread *thread = [[NSThread alloc] initWithBlock:^{
            NSArray<NSString *> *args = @[@"node", script, state, bundle];
            size_t size = 0;
            for (NSString *item in args) size += strlen(item.fileSystemRepresentation) + 1;
            std::vector<char> strings(size);
            std::vector<char *> argv;
            char *next = strings.data();
            for (NSString *item in args) {
                argv.push_back(next);
                strcpy(next, item.fileSystemRepresentation);
                next += strlen(next) + 1;
            }
            argv.push_back(nullptr);
            node_start((int)args.count, argv.data());
        }];
        thread.stackSize = 8 * 1024 * 1024;
        [thread start];
    });
}
@end
