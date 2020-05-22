# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

r"""Convert raw COCO dataset to TFRecord for object_detection.

Please note that this tool creates sharded output files.

Example usage:
    python create_coco_tf_record.py --logtostderr \
      --train_image_dir="${TRAIN_IMAGE_DIR}" \
      --val_image_dir="${VAL_IMAGE_DIR}" \
      --test_image_dir="${TEST_IMAGE_DIR}" \
      --train_annotations_file="${TRAIN_ANNOTATIONS_FILE}" \
      --val_annotations_file="${VAL_ANNOTATIONS_FILE}" \
      --testdev_annotations_file="${TESTDEV_ANNOTATIONS_FILE}" \
      --output_dir="${OUTPUT_DIR}"
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import hashlib
import io
import json
import os
import contextlib2
import numpy as np
import PIL.Image
import sys
sys.path.append("../../models/research")
from pycocotools import mask
import tensorflow as tf
import argparse

from object_detection.dataset_tools import tf_record_creation_util
from object_detection.utils import dataset_util
from object_detection.utils import label_map_util

tf.compat.v1.logging.set_verbosity(tf.compat.v1.logging.INFO)


def create_tf_example(image,
                      annotations_list,
                      image_dir,
                      category_index,
                      include_masks=False):
    """Converts image and annotations to a tf.Example proto.

      Args:
        image: dict with keys:
          [u'license', u'file_name', u'coco_url', u'height', u'width',
          u'date_captured', u'flickr_url', u'id']
        annotations_list:
          list of dicts with keys:
          [u'segmentation', u'area', u'iscrowd', u'image_id',
          u'bbox', u'category_id', u'id']
          Notice that bounding box coordinates in the official COCO dataset are
          given as [x, y, width, height] tuples using absolute coordinates where
          x, y represent the top-left (0-indexed) corner.  This function converts
          to the format expected by the Tensorflow Object Detection API (which is
          which is [ymin, xmin, ymax, xmax] with coordinates normalized relative
          to image size).
        image_dir: directory containing the image files.
        category_index: a dict containing COCO category information keyed
          by the 'id' field of each category.  See the
          label_map_util.create_category_index function.
        include_masks: Whether to include instance segmentations masks
          (PNG encoded) in the result. default: False.
      Returns:
        example: The converted tf.Example
        num_annotations_skipped: Number of (invalid) annotations that were ignored.

      Raises:
        ValueError: if the image pointed to by data['filename'] is not a valid JPEG
      """
    image_height = image['height']
    image_width = image['width']
    filename = image['file_name']
    image_id = image['id']
    full_path = os.path.join(image_dir, filename)

    with tf.io.gfile.GFile(full_path, 'rb') as fid:
        encoded_jpg = fid.read()
        encoded_jpg_io = io.BytesIO(encoded_jpg)
        image = PIL.Image.open(encoded_jpg_io)
        key = hashlib.sha256(encoded_jpg).hexdigest()

    xmin = []
    xmax = []
    ymin = []
    ymax = []
    is_crowd = []
    category_names = []
    category_ids = []
    area = []
    encoded_mask_png = []
    num_annotations_skipped = 0

    for object_annotations in annotations_list:
        (x, y, width, height) = tuple(object_annotations['bbox'])
        if width <= 0 or height <= 0:
            num_annotations_skipped += 1
            continue
        if x + width > image_width or y + height > image_height:
            num_annotations_skipped += 1
            continue
        xmin.append(float(x) / image_width)
        xmax.append(float(x + width) / image_width)
        ymin.append(float(y) / image_height)
        ymax.append(float(y + height) / image_height)
        is_crowd.append(object_annotations['iscrowd'])
        category_id = int(object_annotations['category_id'])
        category_ids.append(category_id)
        category_names.append(category_index[category_id]['name'].encode('utf8'))
        area.append(object_annotations['area'])

        if include_masks:
            run_len_encoding = mask.frPyObjects(object_annotations['segmentation'],
                                          image_height, image_width)
            binary_mask = mask.decode(run_len_encoding)
            if not object_annotations['iscrowd']:
                binary_mask = np.amax(binary_mask, axis=2)
            pil_image = PIL.Image.fromarray(binary_mask)
            output_io = io.BytesIO()
            pil_image.save(output_io, format='PNG')
            encoded_mask_png.append(output_io.getvalue())
    feature_dict = {
      'image/height':
          dataset_util.int64_feature(image_height),
      'image/width':
          dataset_util.int64_feature(image_width),
      'image/filename':
          dataset_util.bytes_feature(filename.encode('utf8')),
      'image/source_id':
          dataset_util.bytes_feature(str(image_id).encode('utf8')),
      'image/key/sha256':
          dataset_util.bytes_feature(key.encode('utf8')),
      'image/encoded':
          dataset_util.bytes_feature(encoded_jpg),
      'image/format':
          dataset_util.bytes_feature('jpeg'.encode('utf8')),
      'image/object/bbox/xmin':
          dataset_util.float_list_feature(xmin),
      'image/object/bbox/xmax':
          dataset_util.float_list_feature(xmax),
      'image/object/bbox/ymin':
          dataset_util.float_list_feature(ymin),
      'image/object/bbox/ymax':
          dataset_util.float_list_feature(ymax),
      'image/object/class/text':
          dataset_util.bytes_list_feature(category_names),
      'image/object/is_crowd':
          dataset_util.int64_list_feature(is_crowd),
      'image/object/area':
          dataset_util.float_list_feature(area),
  }
    if include_masks:
        feature_dict['image/object/mask'] = (
            dataset_util.bytes_list_feature(encoded_mask_png))
    example = tf.train.Example(features=tf.train.Features(feature=feature_dict))

    return key, example, num_annotations_skipped


def _create_tf_record_from_coco_annotations(
        annotations_file, image_dir, output_path, include_masks, num_shards):
    """Loads COCO annotation json files and converts to tf.Record format.

    Args:
        annotations_file: JSON file containing bounding box annotations.
        image_dir: Directory containing the image files.
        output_path: Path to output tf.Record file.
        include_masks: Whether to include instance segmentations masks
          (PNG encoded) in the result. default: False.
        num_shards: number of output file shards.
    """

    with contextlib2.ExitStack() as tf_record_close_stack, tf.io.gfile.GFile(annotations_file, 'r') as fid:
        output_tfrecords = tf_record_creation_util.open_sharded_output_tfrecords(
                tf_record_close_stack, output_path, num_shards)
        groundtruth_data = json.load(fid)
        images = groundtruth_data['images']
        category_index = label_map_util.create_category_index(
            groundtruth_data['categories'])

        annotations_index = {}
        if 'annotations' in groundtruth_data:
            tf.compat.v1.logging.info(
                'Found groundtruth annotations. Building annotations index.')

        for annotation in groundtruth_data['annotations']:
            image_id = annotation['image_id']
            if image_id not in annotations_index:
                annotations_index[image_id] = []
            annotations_index[image_id].append(annotation)
        missing_annotation_count = 0

        for image in images:
            image_id = image['id']
            if image_id not in annotations_index:
                missing_annotation_count += 1
                annotations_index[image_id] = []

        tf.compat.v1.logging.info('%d images are missing annotations.',
                    missing_annotation_count)

        total_num_annotations_skipped = 0
        for idx, image in enumerate(images):
            if idx % 100 == 0:
                tf.compat.v1.logging.info('On image %d of %d', idx, len(images))
            annotations_list = annotations_index[image['id']]
            _, tf_example, num_annotations_skipped = create_tf_example(
                    image, annotations_list, image_dir, category_index, include_masks)
            total_num_annotations_skipped += num_annotations_skipped
            shard_idx = idx % num_shards
            output_tfrecords[shard_idx].write(tf_example.SerializeToString())
        tf.compat.v1.logging.info('Finished writing, skipped %d annotations.', total_num_annotations_skipped)


def main():
    parse = argparse.ArgumentParser(description="Convert coco format to tfrecord format")
    parse.add_argument('--include_masks', default=True,
                          help='Whether to include instance segmentations masks'
                          '(PNG encoded) in the result. default: False.')
    parse.add_argument('--train_image_dir',default= '',
                         help='Training image directory.')
    parse.add_argument('--val_image_dir', default='',
                         help='Validation image directory.')
    # parse.add_argument('--test_image_dir', default='',
    #                      help='Test image directory.')
    parse.add_argument('--train_annotations_file', default='',
                         help='Training annotations JSON file.')
    parse.add_argument('--val_annotations_file', default='',
                         help='Validation annotations JSON file.')
    # parse.add_argument('--testdev_annotations_file', default='',
    #                      help='Test-dev annotations JSON file.')
    parse.add_argument('--output_dir', default='/tmp/', help='Output data directory.')

    args = parse.parse_args()
    if not tf.io.gfile.isdir(args.output_dir):
        tf.io.gfile.makedirs(args.output_dir)
    train_output_path = os.path.join(args.output_dir, 'coco_train.record')
    val_output_path = os.path.join(args.output_dir, 'coco_val.record')
    # testdev_output_path = os.path.join(args.output_dir, 'coco_testdev.record')

    _create_tf_record_from_coco_annotations(
        args.train_annotations_file,
        args.train_image_dir,
        train_output_path,
        args.include_masks,
        num_shards=10)
    _create_tf_record_from_coco_annotations(
        args.val_annotations_file,
        args.val_image_dir,
        val_output_path,
        args.include_masks,
        num_shards=10)
    # _create_tf_record_from_coco_annotations(
    #     args.testdev_annotations_file,
    #     args.test_image_dir,
    #     testdev_output_path,
    #     args.include_masks,
    #     num_shards=10)


if __name__ == '__main__':
    main()
