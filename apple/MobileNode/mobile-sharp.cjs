'use strict';
// Text routing works without libvips. Report image conversion as unavailable
// if a caller actually requests it instead of claiming to transform an image.
module.exports = function mobileImageConversion() {
  throw new Error('Image conversion is unavailable in the mobile gateway');
};
