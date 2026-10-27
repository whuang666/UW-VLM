---
license: apache-2.0
task_categories:
- robotics
tags:
- lerobot
- underwater-robotics
- simulation
- vla
- manipulation
- navigation
pretty_name: USIM
size_categories:
- 100K<n<1M
language:
- en
---

# USIM: Underwater Simulation Dataset for Vision-Language-Action Models

[![Paper](https://img.shields.io/badge/arXiv-2510.07869-B31B1B.svg)](https://arxiv.org/abs/2510.07869)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

## TL;DR

USIM is a large-scale underwater robot manipulation and navigation dataset collected in the [Stonefish](https://github.com/patrykcieslak/stonefish) physics simulator. It contains **2,275 episodes** (1,750 train + 525 test) across **20 tasks** in 9 underwater scenarios, formatted in [LeRobot v2.1](https://github.com/huggingface/lerobot) format with dual-camera video recordings.

## Dataset Description

USIM is introduced in the paper **"USIM and U0: A Vision-Language-Action Dataset and Model for General Underwater Robots"**. It is designed to train and evaluate Vision-Language-Action (VLA) models for autonomous underwater robots operating in diverse subsea environments.

### Key Features

- **Diverse underwater scenarios**: shallow ocean, underwater factory, industrial pool, subsea pipeline, shipwreck sites, lake environments, and open sea
- **Dual-camera observation**: ego (front-facing) and wrist (end-effector) camera views at 240×320 resolution
- **Rich proprioceptive state**: 29-dimensional state vector including joint positions, thruster PWM, velocities, IMU data, DVL, and pressure readings
- **20 tasks** spanning grasping, navigation, tracking, and transporting

### Robot Platform

The robot used is a BlueROV2 underwater vehicle equipped with a 4-DOF robotic arm and a scaled-down Robotiq gripper, simulated in the [Stonefish](https://github.com/patrykcieslak/stonefish) physics engine.

## Dataset Structure

This repository contains two independent LeRobot v2.1 datasets:

```
usim/
├── train/                    # Training split (1,750 episodes)
│   ├── meta/
│   │   ├── info.json
│   │   ├── tasks.jsonl
│   │   ├── episodes.jsonl
│   │   ├── episodes_stats.jsonl
│   │   └── modality.json
│   ├── data/
│   │   ├── chunk-000/
│   │   └── chunk-001/
│   └── videos/
│       ├── chunk-000/
│       │   ├── observation.images.ego/
│       │   └── observation.images.wrist/
│       └── chunk-001/
│           ├── observation.images.ego/
│           └── observation.images.wrist/
├── test/                     # Test split (525 episodes)
│   ├── meta/
│   ├── data/
│   │   └── chunk-000/
│   └── videos/
│       └── chunk-000/
│           ├── observation.images.ego/
│           └── observation.images.wrist/
└── README.md
```

## Supported Tasks

The dataset covers 20 tasks and 9 language instructions grouped into 4 categories:

### Grasping
| Task Code | Instruction | Scenario |
|-----------|-------------|----------|
| pick_pipe0_shallow | Pick up the pipe | Shallow ocean |
| pick_pipe1_shallow | Pick up the pipe | Shallow ocean |
| pick_pipe0_factory | Pick up the pipe | Underwater factory |
| pick_pipe1_factory | Pick up the pipe | Underwater factory |
| pick_red_shallow | Pick up the red cylinder | Shallow ocean |
| pick_redx_shallow | Pick up the red cylinder | Shallow ocean (multi-blue distractors) |
| pick_red_factory | Pick up the red cylinder | Underwater factory |
| pick_redx_factory | Pick up the red cylinder | Underwater factory (multi-blue distractors) |
| pick_blue_shallow | Pick up the blue cylinder | Shallow ocean |
| pick_bluex_shallow | Pick up the blue cylinder | Shallow ocean (multi-red distractors) |
| pick_blue_factory | Pick up the blue cylinder | Underwater factory |
| pick_bluex_factory | Pick up the blue cylinder | Underwater factory (multi-red distractors) |

### Navigation
| Task Code | Instruction | Scenario |
|-----------|-------------|----------|
| goto_charge_station | Go to the charge station | Lake with equipment |
| goto_water_tower | Go to the water tower | Lake with rocks |
| scan_ship_modern | Scan the ship | Modern shipwreck |
| scan_ship_ancient | Scan the ship | Ancient shipwreck |
| inspect_pipeline_pool | Inspect the pipeline | Industrial pool with pipelines |
| inspect_pipeline_sea | Inspect the pipeline | Subsea pipeline |

### Tracking
| Task Code | Instruction | Scenario |
|-----------|-------------|----------|
| follow_boat | Follow the boat | Open sea |

### Transporting
| Task Code | Instruction | Scenario |
|-----------|-------------|----------|
| transfer_red_shallow | Pick up the red cylinder and transfer it to the box | Shallow ocean |

## Data Statistics

### Overall

| Metric | Train | Test | Total |
|--------|-------|------|-------|
| Episodes | 1,750 | 525 | 2,275 |
| Frames | 696,990 | 208,605 | 905,595 |
| Videos | 3,500 | 1,050 | 4,550 |

### Per-Task Breakdown

| Task | Train Episodes | Train Frames | Test Episodes | Test Frames |
|------|---------------|--------------|---------------|-------------|
| follow_boat | 50 | 18,061 | 15 | 5,026 |
| goto_charge_station | 100 | 13,371 | 30 | 4,437 |
| goto_water_tower | 100 | 29,505 | 30 | 9,084 |
| inspect_pipeline_pool | 50 | 29,609 | 15 | 8,828 |
| inspect_pipeline_sea | 50 | 33,884 | 15 | 10,156 |
| pick_blue_factory | 100 | 38,038 | 30 | 11,857 |
| pick_blue_shallow | 100 | 35,953 | 30 | 11,371 |
| pick_bluex_factory | 100 | 38,461 | 30 | 11,505 |
| pick_bluex_shallow | 100 | 38,486 | 30 | 10,843 |
| pick_pipe0_factory | 100 | 38,683 | 30 | 10,942 |
| pick_pipe0_shallow | 100 | 37,205 | 30 | 11,411 |
| pick_pipe1_factory | 100 | 36,997 | 30 | 11,113 |
| pick_pipe1_shallow | 100 | 37,025 | 30 | 10,963 |
| pick_red_factory | 100 | 37,829 | 30 | 11,645 |
| pick_red_shallow | 100 | 36,914 | 30 | 10,990 |
| pick_redx_factory | 100 | 38,455 | 30 | 11,433 |
| pick_redx_shallow | 100 | 36,428 | 30 | 10,398 |
| scan_ship_ancient | 50 | 37,046 | 15 | 11,008 |
| scan_ship_modern | 50 | 33,868 | 15 | 10,285 |
| transfer_red_shallow | 100 | 51,172 | 30 | 15,310 |
| **Total** | **1,750** | **696,990** | **525** | **208,605** |

## Data Schema

Both `train/` and `test/` follow the [LeRobot v2.1](https://github.com/huggingface/lerobot) format. Each episode is stored as a Parquet file with the following features:

### Observation

| Feature | Dtype | Shape | Description |
|---------|-------|-------|-------------|
| `observation.images.ego` | video | (240, 320, 3) | Front-facing ego camera RGB video |
| `observation.images.wrist` | video | (240, 320, 3) | Wrist-mounted end-effector camera RGB video |
| `observation.state` | float32 | (29,) | Robot proprioceptive state vector |

#### State Vector Breakdown (29-dim)

| Component | Indices | Dim | Description |
|-----------|---------|-----|-------------|
| `joint_pos` | 0–5 | 6 | Arm joint positions |
| `pwm` | 5–13 | 8 | Thruster PWM values |
| `joint_v` | 13–18 | 5 | Arm joint velocities |
| `dvl_v` | 18–21 | 3 | Doppler Velocity Log velocity |
| `imu_av` | 21–24 | 3 | IMU angular velocity |
| `imu_la` | 24–27 | 3 | IMU linear acceleration |
| `pressure` | 27–28 | 1 | Pressure sensor reading |
| `dvl_h` | 28–29 | 1 | DVL altitude |

### Action

| Feature | Dtype | Shape | Description |
|---------|-------|-------|-------------|
| `action` | float32 | (13,) | Robot action command |

#### Action Breakdown (13-dim)

| Component | Indices | Dim | Description |
|-----------|---------|-----|-------------|
| `joint_pos` | 0–5 | 6 | Arm target joint positions |
| `pwm` | 5–13 | 8 | Thruster PWM commands |

### Additional Features

| Feature | Dtype | Shape | Description |
|---------|-------|-------|-------------|
| `target_pos` | float32 | (6,) | Target pose in robot local frame (x, y, z, roll, pitch, yaw) |
| `timestamp` | float32 | (1,) | Frame timestamp in seconds |
| `frame_index` | int64 | (1,) | Frame index within episode |
| `episode_index` | int64 | (1,) | Episode index |
| `index` | int64 | (1,) | Global frame index |
| `task_index` | int64 | (1,) | Task index (maps to `tasks.jsonl`) |

### Video Metadata

| Property | Value |
|----------|-------|
| Resolution | 240 × 320 |
| Codec | AV1 |
| Pixel Format | YUV420P |
| FPS | 10 |
| Channels | 3 (RGB) |
| Audio | No |

## Loading the Dataset

### Using LeRobot

```python
from lerobot.common.datasets.lerobot_dataset import LeRobotDataset

# Load the training split
train_dataset = LeRobotDataset("Vincent2025hello/usim", root="train")

# Load the test split
test_dataset = LeRobotDataset("Vincent2025hello/usim", root="test")

# Iterate through episodes
for episode in train_dataset:
    ego_image = episode["observation.images.ego"]       # (240, 320, 3) numpy array
    wrist_image = episode["observation.images.wrist"]   # (240, 320, 3) numpy array
    state = episode["observation.state"]                # (29,) numpy array
    action = episode["action"]                          # (13,) numpy array
    task_index = episode["task_index"]                  # scalar
    print(f"Task: {train_dataset.meta.tasks[task_index]}")
```

### Using Hugging Face Datasets

```python
from datasets import load_dataset

# Load from the repository
dataset = load_dataset("Vincent2025hello/usim")
```

## Citation

If you use this dataset in your research, please cite:

```bibtex
@misc{gu2025usimu0visionlanguageactiondataset,
      title={USIM and U0: A Vision-Language-Action Dataset and Model for General Underwater Robots}, 
      author={Junwen Gu and Zhiheng Wu and Pengxuan Si and Shuang Qiu and Yukai Feng and Luoyang Sun and Laien Luo and Lianyi Yu and Jian Wang and Zhengxing Wu},
      year={2025},
      eprint={2510.07869},
      archivePrefix={arXiv},
      primaryClass={cs.RO},
      url={https://arxiv.org/abs/2510.07869}, 
}
```

## License

This dataset is released under the [Apache 2.0 License](https://opensource.org/licenses/Apache-2.0).

## Acknowledgements

- [Stonefish](https://github.com/patrykcieslak/stonefish) — Physics-based underwater simulator
- [stonefish_ros](https://github.com/patrykcieslak/stonefish_ros) — ROS interface for Stonefish
- [LeRobot](https://github.com/huggingface/lerobot) — Dataset format and loading utilities