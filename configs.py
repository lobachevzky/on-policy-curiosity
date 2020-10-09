import copy
import json

from hyperopt import hp

with open("lower.json") as f:
    default_lower = json.load(f)

default_upper = {
    "break_on_fail": False,
    "clip_param": 0.2,
    "conv_hidden_size": 64,
    "cuda": True,
    "cuda_deterministic": False,
    "debug": False,
    "entropy_coef": 0.01,
    "env_id": "control-flow",
    "eps": 1e-5,
    "eval_interval": 100,
    "eval_steps": 500,
    "failure_buffer_size": 500,
    "gamma": 0.99,
    "gate_coef": 0.01,
    "hidden_size": 256,
    "inventory_hidden_size": 128,
    "kernel_size": 1,
    "learning_rate": 0.003,
    "load_path": None,
    "log_interval": 10,
    "lower_embed_size": 64,
    "lower_level_config": "lower.json",
    "lower_level_load_path": "lower.pt",
    "max_eval_lines": 50,
    "tgt_success_rate": 0.8,
    "max_grad_norm": 0.5,
    "max_lines": 10,
    "min_eval_lines": 1,
    "min_lines": 1,
    "no_op_coef": 0,
    "no_op_limit": 40,
    "no_pointer": False,
    "no_roll": False,
    "no_scan": False,
    "normalize": False,
    "num_batch": 1,
    "num_edges": 2,
    "num_frames": 200,
    "num_layers": 0,
    "num_processes": 150,
    "olsk": False,
    "ppo_epoch": 3,
    "recurrent": False,
    "save_interval": None,
    "seed": 0,
    "stride": 1,
    "synchronous": False,
    "task_embed_size": 64,
    "tau": 0.95,
    "train_steps": 30,
    "transformer": False,
    "use_gae": False,
    "value_loss_coef": 0.5,
    "room_side": 4,
    "bridge_failure_prob": 0,
    "map_discovery_prob": 0,
    "bandit_prob": 0,
    "windfall_prob": 0,
    # "bridge_failure_prob": 0.25,
    # "map_discovery_prob": 0.02,
    # "bandit_prob": 0.005,
    # "windfall_prob": 0.25,
}

upper_search = copy.deepcopy(default_upper)
upper_search.update(
    conv_hidden_size=hp.choice("conv_hidden_size", [32, 64, 128]),
    entropy_coef=hp.choice("entropy_coef", [0.01, 0.015, 0.02]),
    gate_coef=hp.choice("gate_coef", [0, 0.01, 0.05]),
    hidden_size=hp.choice("hidden_size", [128, 256, 512]),
    inventory_hidden_size=hp.choice("inventory_hidden_size", [64, 128, 256]),
    kernel_size=hp.choice("kernel_size", [1, 2, 3]),
    learning_rate=hp.choice("learning_rate", [0.002, 0.003, 0.004]),
    lower_embed_size=hp.choice("lower_embed_size", [32, 64, 128]),
    max_failure_sample_prob=hp.choice("max_failure_sample_prob", [0.2, 0.3, 0.4]),
    max_while_loops=hp.choice("max_while_loops", [5, 10, 15]),
    no_op_limit=hp.choice("no_op_limit", [20, 30, 40]),
    num_batch=hp.choice("num_batch", [1, 2]),
    num_edges=hp.choice("num_edges", [2, 4, 6]),
    num_processes=hp.choice("num_processes", [50, 100, 150]),
    ppo_epoch=hp.choice("ppo_epoch", [1, 2, 3]),
    reject_while_prob=hp.choice("reject_while_prob", [0.5, 0.6]),
    stride=hp.choice("stride", [1, 2, 3]),
    task_embed_size=hp.choice("task_embed_size", [32, 64, 128]),
    train_steps=hp.choice("train_steps", [20, 25, 30]),
    use_gae=hp.choice("use_gae", [True, False]),
)

lower_search = copy.deepcopy(default_lower)
lower_search.update(
    conv_hidden_size=hp.choice("conv_hidden_size", [32, 64, 128]),
    entropy_coef=hp.choice("entropy_coef", [0.01, 0.015, 0.02]),
    hidden_size=hp.choice("hidden_size", [128, 256, 512]),
    kernel_size=hp.choice("kernel_size", [2, 3]),
    learning_rate=hp.choice("learning_rate", [0.002, 0.003, 0.004]),
    tgt_success_rate=hp.choice("tgt_success_rate", [0.5, 0.7, 0.8, 0.9, 1]),
    num_batch=hp.choice("num_batch", [1, 2]),
    num_conv_layers=hp.choice("num_conv_layers", [1, 2]),
    num_layers=hp.choice("num_layers", [1, 2]),
    num_processes=hp.choice("num_processes", [50, 100, 150]),
    ppo_epoch=hp.choice("ppo_epoch", [1, 2, 3]),
    stride=hp.choice("stride", [1, 2]),
    train_steps=hp.choice("train_steps", [20, 25, 30]),
    use_gae=hp.choice("use_gae", [True, False]),
)

debug_search = copy.deepcopy(upper_search)
debug_search.update(
    kernel_size=1,
    stride=1,
    world_size=1,
)
debug_default = copy.deepcopy(default_upper)
debug_default.update(
    kernel_size=1,
    stride=1,
    world_size=1,
)
configs = dict(
    lower_search=lower_search,
    upper_search=upper_search,
    debug_search=debug_search,
    default_upper=default_upper,
    debug_default=debug_default,
)
