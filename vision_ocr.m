#import <Foundation/Foundation.h>
#import <Vision/Vision.h>
#import <CoreGraphics/CoreGraphics.h>
#import <ImageIO/ImageIO.h>
#import <math.h>
#import <stdlib.h>

static NSArray *RecognizePage(CGPDFPageRef page, NSError **error) {
    CGRect box = CGPDFPageGetBoxRect(page, kCGPDFMediaBox);
    const CGFloat scale = 2.5;
    size_t width = (size_t)ceil(box.size.width * scale);
    size_t height = (size_t)ceil(box.size.height * scale);
    CGColorSpaceRef colorSpace = CGColorSpaceCreateDeviceRGB();
    CGContextRef context = CGBitmapContextCreate(NULL, width, height, 8, width * 4,
        colorSpace, kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big);
    CGColorSpaceRelease(colorSpace);
    if (!context) return @[];
    CGContextSetRGBFillColor(context, 1, 1, 1, 1);
    CGContextFillRect(context, CGRectMake(0, 0, width, height));
    CGContextScaleCTM(context, scale, scale);
    CGContextTranslateCTM(context, -box.origin.x, -box.origin.y);
    CGContextDrawPDFPage(context, page);
    CGImageRef image = CGBitmapContextCreateImage(context);
    CGContextRelease(context);
    const char *testImage = getenv("OCR_TEST_IMAGE");
    if (testImage) {
        NSURL *testURL = [NSURL fileURLWithPath:[NSString stringWithUTF8String:testImage]];
        CGImageSourceRef source = CGImageSourceCreateWithURL((__bridge CFURLRef)testURL, NULL);
        CGImageRef loaded = source ? CGImageSourceCreateImageAtIndex(source, 0, NULL) : NULL;
        if (source) CFRelease(source);
        if (loaded) { if (image) CGImageRelease(image); image = loaded; }
    }
    const char *debugPath = getenv("OCR_DEBUG_PATH");
    if (debugPath && image) {
        NSURL *debugURL = [NSURL fileURLWithPath:[NSString stringWithUTF8String:debugPath]];
        CGImageDestinationRef dest = CGImageDestinationCreateWithURL((__bridge CFURLRef)debugURL, CFSTR("public.png"), 1, NULL);
        if (dest) { CGImageDestinationAddImage(dest, image, NULL); CGImageDestinationFinalize(dest); CFRelease(dest); }
    }

    VNRecognizeTextRequest *request = [[VNRecognizeTextRequest alloc] init];
    NSError *languagesError = nil;
    NSArray *supportedLanguages = [VNRecognizeTextRequest supportedRecognitionLanguagesForTextRecognitionLevel:VNRequestTextRecognitionLevelAccurate revision:VNRecognizeTextRequestRevision3 error:&languagesError];
    if (getenv("OCR_DEBUG_PATH") || getenv("OCR_TEST_IMAGE")) fprintf(stderr, "Vision supported languages=%lu error=%s\n", (unsigned long)supportedLanguages.count, languagesError.localizedDescription.UTF8String ?: "(none)");
    request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
    request.usesLanguageCorrection = YES;
    request.recognitionLanguages = @[@"en-US"];
    request.minimumTextHeight = 0.004;
    VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithCGImage:image options:@{}];
    NSError *performError = nil;
    BOOL ok = [handler performRequests:@[request] error:&performError];
    if (error && performError) *error = performError;
    if (getenv("OCR_DEBUG_PATH") || getenv("OCR_TEST_IMAGE")) fprintf(stderr, "Vision request ok=%d image=%zux%zu observations=%lu requestError=%s\n", ok, CGImageGetWidth(image), CGImageGetHeight(image), (unsigned long)request.results.count, performError.localizedDescription.UTF8String ?: "(none)");
    CGImageRelease(image);
    if (!ok) return @[];

    NSMutableArray *lines = [NSMutableArray array];
    for (VNRecognizedTextObservation *observation in request.results) {
        VNRecognizedText *candidate = [[observation topCandidates:1] firstObject];
        if (!candidate || candidate.string.length == 0) continue;
        CGRect r = observation.boundingBox;
        [lines addObject:@{
            @"text": candidate.string,
            @"confidence": @(candidate.confidence),
            @"x": @(r.origin.x),
            @"top": @(1.0 - r.origin.y - r.size.height),
            @"width": @(r.size.width),
            @"height": @(r.size.height)
        }];
    }
    [lines sortUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) {
        CGFloat ya = [a[@"top"] doubleValue], yb = [b[@"top"] doubleValue];
        if (fabs(ya - yb) > 0.004) return ya < yb ? NSOrderedAscending : NSOrderedDescending;
        CGFloat xa = [a[@"x"] doubleValue], xb = [b[@"x"] doubleValue];
        return xa < xb ? NSOrderedAscending : (xa > xb ? NSOrderedDescending : NSOrderedSame);
    }];
    return lines;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc < 2) { fprintf(stderr, "Usage: vision_ocr <pdf-path> [first-page] [last-page]\n"); return 2; }
        NSString *path = [NSString stringWithUTF8String:argv[1]];
        NSURL *url = [NSURL fileURLWithPath:path];
        CGPDFDocumentRef doc = CGPDFDocumentCreateWithURL((__bridge CFURLRef)url);
        if (!doc) { fprintf(stderr, "Could not open PDF\n"); return 3; }
        size_t count = CGPDFDocumentGetNumberOfPages(doc);
        size_t first = argc > 2 ? (size_t)MAX(1, atoi(argv[2])) : 1;
        size_t last = argc > 3 ? (size_t)MAX((int)first, atoi(argv[3])) : count;
        last = MIN(last, count);
        NSMutableArray *pages = [NSMutableArray array];
        for (size_t i = first; i <= last; i++) {
            @autoreleasepool {
                NSError *error = nil;
                NSArray *lines = RecognizePage(CGPDFDocumentGetPage(doc, i), &error);
                if (error) fprintf(stderr, "OCR page %zu: %s\n", i, error.localizedDescription.UTF8String);
                [pages addObject:@{@"page": @(i), @"lines": lines ?: @[]}];
            }
        }
        CGPDFDocumentRelease(doc);
        NSData *json = [NSJSONSerialization dataWithJSONObject:@{@"pages": pages} options:NSJSONWritingFragmentsAllowed error:nil];
        fwrite(json.bytes, 1, json.length, stdout); fputc('\n', stdout);
    }
    return 0;
}
