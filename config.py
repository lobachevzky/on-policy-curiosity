from collections import namedtuple

from hydra.core.config_store import ConfigStore
from omegaconf import MISSING, DictConfig

Parsers = namedtuple("Parser", "main agent ppo rollouts")


from dataclasses import dataclass, field
from typing import Optional, Any, List


def flatten(cfg: DictConfig):
    for k, v in cfg.items():
        if isinstance(v, DictConfig):
            for k_, v_ in flatten(v):
                yield f"{k}_{k_}", v_
        else:
            yield k, v


@dataclass
class Eval:
    interval: Optional[int] = MISSING
    steps: Optional[int] = MISSING


@dataclass
class NoEval(Eval):
    interval: Optional[int] = None
    steps: Optional[int] = None


@dataclass
class YesEval(Eval):
    interval: Optional[int] = int(1e5)
    steps: Optional[int] = 500


@dataclass
class BaseConfig:
    activation_name: str = "ReLU"
    clip_param: float = 0.2
    cuda_deterministic: bool = True
    entropy_coef: float = 0.25
    eval: Any = MISSING
    gamma: float = 0.99
    group: Optional[str] = None
    hidden_size: int = 150
    learning_rate: float = 0.0025
    load_path: Optional[str] = None
    log_interval: int = int(1e5)
    max_grad_norm: float = 0.5
    name: Optional[str] = None
    normalize: bool = False
    num_batch: int = 1
    num_processes: int = 100
    optimizer: str = "Adam"
    ppo_epoch: int = 5
    cuda: bool = True
    use_wandb: bool = True
    num_frames: Optional[int] = None
    render: bool = False
    render_eval: bool = False
    save_interval: int = int(1e5)
    seed: int = 0
    synchronous: bool = False
    tau: float = 0.95
    train_steps: int = 25
    use_gae: bool = False
    value_loss_coef: float = 0.5
    wandb_version: Optional[str] = None
    _wandb: Optional[str] = None
    defaults: List[Any] = field(default_factory=lambda: [dict(eval="yes")])


@dataclass
class Config(BaseConfig):
    env: str = "CartPole-v0"
    num_layers: int = 100
    recurrent: bool = False


cs = ConfigStore.instance()
cs.store(group="eval", name="yes", node=YesEval)
cs.store(group="eval", name="no", node=NoEval)
