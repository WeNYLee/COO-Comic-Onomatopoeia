# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
import argparse
import glob
import multiprocessing as mp
import numpy as np
import os
import time
import cv2
import tqdm

from detectron2.data.detection_utils import read_image
from detectron2.structures import Boxes
from detectron2.utils.logger import setup_logger

from predictor import VisualizationDemo
from adet.config import get_cfg

from detectron2.config import CfgNode

# constants
WINDOW_NAME = "COCO detections"


def add_custom_configs(cfg: CfgNode):
    _C = cfg
    _C.SOLVER.BEST_CHECKPOINTER = CfgNode({"ENABLED": False})
    _C.SOLVER.BEST_CHECKPOINTER.METRIC = "bbox/AP50"
    _C.SOLVER.BEST_CHECKPOINTER.MODE = "max"
    _C.TRAIN_LOG_PERIOD = 200


def setup_cfg(args):
    # load config from file and command-line arguments
    cfg = get_cfg()
    add_custom_configs(cfg)
    cfg.merge_from_file(args.config_file)
    cfg.merge_from_list(args.opts)
    # Set score_threshold for builtin models
    cfg.MODEL.RETINANET.SCORE_THRESH_TEST = args.confidence_threshold
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = args.confidence_threshold
    cfg.MODEL.FCOS.INFERENCE_TH_TEST = args.confidence_threshold
    cfg.MODEL.MEInst.INFERENCE_TH_TEST = args.confidence_threshold
    cfg.MODEL.PANOPTIC_FPN.COMBINE.INSTANCES_CONFIDENCE_THRESH = (
        args.confidence_threshold
    )
    cfg.freeze()
    return cfg


def get_parser():
    parser = argparse.ArgumentParser(description="Detectron2 Demo")
    parser.add_argument(
        "--config-file",
        default="configs/quick_schedules/e2e_mask_rcnn_R_50_FPN_inference_acc_test.yaml",
        metavar="FILE",
        help="path to config file",
    )
    parser.add_argument(
        "--webcam", action="store_true", help="Take inputs from webcam."
    )
    parser.add_argument("--video-input", help="Path to video file.")
    parser.add_argument(
        "--input", nargs="+", help="A list of space separated input images"
    )
    parser.add_argument(
        "--output",
        help="A file or directory to save output visualizations. "
        "If not given, will show output in an OpenCV window.",
    )

    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.3,
        help="Minimum score for instance predictions to be shown",
    )
    parser.add_argument(
        "--opts",
        help="Modify config options using the command-line 'KEY VALUE' pairs",
        default=[],
        nargs=argparse.REMAINDER,
    )
    return parser

def process_image(img, boxes, output_img_path, output_mask_path):
    img = img.astype(np.uint8)
    mask = np.zeros_like(img)
    output_img = img.copy()

    for box in boxes.tensor:
        x1, y1, x2, y2 = box.int().tolist()
        output_img[y1:y2, x1:x2] = 255
        mask[y1:y2, x1:x2] = 255

    cv2.imwrite(output_img_path, output_img)
    cv2.imwrite(output_mask_path, mask)

if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    args = get_parser().parse_args()
    logger = setup_logger()
    logger.info("Arguments: " + str(args))

    cfg = setup_cfg(args)

    demo = VisualizationDemo(cfg)

    if args.input:
        if os.path.isdir(args.input[0]):
            args.input = [
                os.path.join(args.input[0], fname)
                for fname in os.listdir(args.input[0])
            ]
        elif len(args.input) == 1:
            args.input = glob.glob(os.path.expanduser(args.input[0]))
            assert args.input, "The input path(s) was not found"
        for path in tqdm.tqdm(args.input, disable=not args.output):
            # use PIL, to be consistent with evaluation
            img = read_image(path, format="BGR")
            start_time = time.time()
            predictions, visualized_output = demo.run_on_image(img)
            logger.info(
                "{}: detected {} instances in {:.2f}s".format(
                    path, len(predictions["instances"]), time.time() - start_time
                )
            )

            # make output folder here?
            os.makedirs(args.output, exist_ok=True)

            if args.output:
                if os.path.isdir(args.output):
                    assert os.path.isdir(args.output), args.output
                    out_filename = os.path.join(args.output, os.path.basename(path))
                else:
                    assert (
                        len(args.input) == 1
                    ), "Please specify a directory with args.output"
                    out_filename = args.output

                try:
                    visualized_output.save(out_filename)

                    # create cropped images
                    boxes = predictions["instances"].pred_boxes
                    prefix = os.path.splitext(os.path.basename(path))[0]
                    incomplete_basename = f'{prefix}_incomplete.jpg'
                    incomplete_filename = os.path.join(args.output, incomplete_basename)
                    mask_basename = f'{prefix}_mask.jpg'
                    mask_filename = os.path.join(args.output, mask_basename)

                    try:
                      process_image(img, boxes, incomplete_filename, mask_filename)
                    except Exception as e:
                      print(f'Exception due to {e}')

                    for idx, box in enumerate(boxes):
                      logger.info(f'{idx}, {box}')
                      box = box.tolist()
                      x1, y1, x2, y2 = box
                      logger.info(f'{x1}, {y1}, {x2}, {y2}')
                      cropped_region = img[int(y1):int(y2), int(x1):int(x2)]
                      cropped_basename = os.path.splitext(os.path.basename(path))[0] + f'_cropped_{idx}.jpg'
                      cropped_filename = os.path.join(args.output, cropped_basename)
                      cv2.imwrite(cropped_filename, cropped_region)
                except:
                    print("err not a image? The model is not trained enough?")

            else:
                cv2.imshow(WINDOW_NAME, visualized_output.get_image()[:, :, ::-1])
                if cv2.waitKey(0) == 27:
                    break  # esc to quit
    elif args.webcam:
        assert args.input is None, "Cannot have both --input and --webcam!"
        cam = cv2.VideoCapture(0)
        for vis in tqdm.tqdm(demo.run_on_video(cam)):
            cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
            cv2.imshow(WINDOW_NAME, vis)
            if cv2.waitKey(1) == 27:
                break  # esc to quit
        cv2.destroyAllWindows()
    elif args.video_input:
        video = cv2.VideoCapture(args.video_input)
        width = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frames_per_second = video.get(cv2.CAP_PROP_FPS)
        num_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
        basename = os.path.basename(args.video_input)

        if args.output:
            if os.path.isdir(args.output):
                output_fname = os.path.join(args.output, basename)
                output_fname = os.path.splitext(output_fname)[0] + ".mkv"
            else:
                output_fname = args.output
            assert not os.path.isfile(output_fname), output_fname
            output_file = cv2.VideoWriter(
                filename=output_fname,
                # some installation of opencv may not support x264 (due to its license),
                # you can try other format (e.g. MPEG)
                fourcc=cv2.VideoWriter_fourcc(*"x264"),
                fps=float(frames_per_second),
                frameSize=(width, height),
                isColor=True,
            )
        assert os.path.isfile(args.video_input)
        for vis_frame in tqdm.tqdm(demo.run_on_video(video), total=num_frames):
            if args.output:
                output_file.write(vis_frame)
            else:
                cv2.namedWindow(basename, cv2.WINDOW_NORMAL)
                cv2.imshow(basename, vis_frame)
                if cv2.waitKey(1) == 27:
                    break  # esc to quit
        video.release()
        if args.output:
            output_file.release()
        else:
            cv2.destroyAllWindows()
