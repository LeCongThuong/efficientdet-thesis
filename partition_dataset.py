from shutil import copyfile
import os
import re
import math
import random
import argparse


def iterate_dir(source_dir, des_dir, ratio, cop_xml):
    """
    source_dir: path to image folder
    des_dir: path to folder that contains train and test directory
    ratio: the percentage of test dataset
    cop_xml: True/False: whether copy xml file or not
    """
    train_dir = os.path.join(des_dir, 'train')
    test_dir = os.path.join(des_dir, 'test')

    if os.path.exists(train_dir):
        os.makedirs(train_dir)
    if os.path.exists(test_dir):
        os.makedirs(test_dir)

    images = [f for f in os.listdir(source_dir) if re.search(r'([A-Za-z0-9\s_\\\.:]+)(.jpg|.jpeg|.png)$', f)]
    num_images = len(images)
    num_test_images = math.ceil(ratio*num_images)

    for i in range(num_test_images):
        idx = random.randint(0, len(images) - 1)
        filename = images[idx]
        copyfile(os.path.join(source_dir, filename), os.path.join(test_dir, filename))
        if cop_xml:
            xml_filename = os.path.splitext(filename)[0]+'.xml'
            copyfile(os.path.join(source_dir, xml_filename), os.path.join(test_dir, xml_filename))
        images.remove(images[idx])

    for filename in images:
        copyfile(os.path.join(source_dir, filename),
                              os.path.join(train_dir, filename))
        if cop_xml:
            xml_filename = os.path.splitext(filename)[0]+'xml'
            copyfile(os.path.join(source_dir, xml_filename), os.path.join(des_dir, xml_filename))


def main():
    # Initiate argument parser
    parser = argparse.ArgumentParser(description="Partition dataset of images into training and testing sets",
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        '-i', '--imageDir',
        help='Path to the folder where the image dataset is stored. If not specified, the CWD will be used.',
        type=str,
        default=os.getcwd()
    )
    parser.add_argument(
        '-o', '--outputDir',
        help='Path to the output folder where the train and test dirs should be created. '
             'Defaults to the same directory as IMAGEDIR.',
        type=str,
        default=None
    )
    parser.add_argument(
        '-r', '--ratio',
        help='The ratio of the number of test images over the total number of images. The default is 0.1.',
        default=0.1,
        type=float)
    parser.add_argument(
        '-x', '--xml',
        help='Set this flag if you want the xml annotation files to be processed and copied over.',
        action='store_true'
    )
    args = parser.parse_args()

    if args.outputDir is None:
        args.outputDir = args.imageDir

    # Now we are ready to start the iteration
    iterate_dir(args.imageDir, args.outputDir, args.ratio, args.xml)


if __name__ == '__main__':
    main()




