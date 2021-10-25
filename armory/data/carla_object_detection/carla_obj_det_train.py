import collections
import json
import os
from copy import deepcopy

import tensorflow.compat.v1 as tf
import tensorflow_datasets as tfds

_DESCRIPTION = """
Synthetic multimodality (RGB, depth) dataset generated using CARLA (https://carla.org).
"""

_CITATION = """
@inproceedings{Dosovitskiy17,
  title = { {CARLA}: {An} Open Urban Driving Simulator},
  author = {Alexey Dosovitskiy and German Ros and Felipe Codevilla and Antonio Lopez and Vladlen Koltun},
  booktitle = {Proceedings of the 1st Annual Conference on Robot Learning},
  pages = {1--16},
  year = {2017}
}
"""

# fmt: off
_URLS = "https://armory-public-data.s3.us-east-2.amazonaws.com/carla/carla_OD_train.tar.gz"
# fmt: on


class CarlaObjDetTrain(tfds.core.GeneratorBasedBuilder):
    """DatasetBuilder for carla_obj_det_train dataset."""

    VERSION = tfds.core.Version("1.0.1")
    RELEASE_NOTES = {
        "1.0.0": "Initial release.",
        "1.0.1": "Correcting error to RGB and depth image pairing",
    }

    def _info(self) -> tfds.core.DatasetInfo:
        """Returns the dataset metadata."""
        features = {
            # sequence of [RGB, depth] images
            "image": tfds.features.Sequence(
                tfds.features.Image(shape=(600, 800, 3)), length=2,
            ),
            # sequence of image features for [RGB, depth]
            "images": tfds.features.Sequence(
                tfds.features.FeaturesDict(
                    {
                        "file_name": tfds.features.Text(),
                        "height": tf.int64,
                        "width": tf.int64,
                        "id": tf.int64,
                    },
                ),
                length=2,
            ),
            # both modalities share the same categories
            "categories": tfds.features.Sequence(
                tfds.features.FeaturesDict(
                    {
                        "id": tf.int64,  # {'pedstrian':1, 'vehicles':2, 'trafficlight':3, 'patch':4}
                        "name": tfds.features.Text(),
                    }
                )
            ),
            # both modalities share the same objects
            "objects": tfds.features.Sequence(
                {
                    "id": tf.int64,
                    "image_id": tf.int64,
                    "area": tf.int64,  # un-normalized area
                    "boxes": tfds.features.BBoxFeature(),  # normalized bounding box [ymin, xmin, ymax, xmax]
                    "labels": tfds.features.ClassLabel(num_classes=5),
                    "is_crowd": tf.bool,
                }
            ),
        }

        return tfds.core.DatasetInfo(
            builder=self,
            description=_DESCRIPTION,
            features=tfds.features.FeaturesDict(features),
            citation=_CITATION,
        )

    def _split_generators(self, dl_manager: tfds.download.DownloadManager):
        """Returns SplitGenerators."""
        path = dl_manager.download_and_extract(_URLS)
        return [
            tfds.core.SplitGenerator(
                name="train", gen_kwargs={"path": os.path.join(path, "train")},
            )
        ]

    def _generate_examples(self, path):
        """yield examples"""
        # For each image, gets its annotations and yield relevant data

        yield_id = 0

        annotation_path = os.path.join(path, "annotations/coco_annotations.json")

        cocoanno = COCOAnnotation(annotation_path)

        images_rgb = (
            cocoanno.images()
        )  # list of dictionaries of RGB image id, height, width, file_name

        # sort images alphabetically
        images_rgb = sorted(images_rgb, key=lambda x: x["file_name"].lower())

        for image_rgb in images_rgb:

            # verify RGB and depth are paired
            fname_rgb = image_rgb["file_name"]  # rgb image file
            fname, fext = fname_rgb.split(".")
            fname_depth = fname + "_Depth." + fext  # depth image file
            image_depth = deepcopy(image_rgb)
            image_depth["file_name"] = fname_depth

            # get object annotations for each image
            annotations = cocoanno.get_annotations(image_rgb["id"])

            # convert bbox to Tensorflow format
            def build_bbox(x, y, width, height):
                return tfds.features.BBox(
                    ymin=y / image_rgb["height"],
                    xmin=x / image_rgb["width"],
                    ymax=(y + height) / image_rgb["height"],
                    xmax=(x + width) / image_rgb["width"],
                )

            example = {
                "image": [
                    os.path.join(path, modality,)
                    for modality in [fname_rgb, fname_depth]
                ],
                "images": [image_rgb, image_depth],
                "categories": cocoanno.categories(),
                "objects": [
                    {
                        "id": anno["id"],
                        "image_id": anno["image_id"],
                        "area": anno["areas"],
                        "boxes": build_bbox(*anno["bbox"]),
                        "labels": anno["category_id"],
                        "is_crowd": bool(anno["iscrowd"]),
                    }
                    for anno in annotations
                ],
            }

            yield_id = yield_id + 1

            yield yield_id, example


class COCOAnnotation(object):
    """COCO annotation helper class."""

    def __init__(self, annotation_path):
        with tf.io.gfile.GFile(annotation_path) as f:
            data = json.load(f)
        self._data = data

        # for each images["id"], find all annotations such that annotations["image_id"] == images["id"]
        img_id2annotations = collections.defaultdict(list)
        for a in self._data["annotations"]:
            img_id2annotations[a["image_id"]].append(a)
        self._img_id2annotations = {
            k: list(sorted(v, key=lambda a: a["id"]))
            for k, v in img_id2annotations.items()
        }

    def categories(self):
        """Return the category dicts, as sorted in the file."""
        return self._data["categories"]

    def images(self):
        """Return the image dicts, as sorted in the file."""
        return self._data["images"]

    def get_annotations(self, img_id):
        """Return all annotations associated with the image id string."""
        return self._img_id2annotations.get(img_id, [])