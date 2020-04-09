import torch
import torch.jit
from gym import spaces
from gym.spaces import Box
from torch import nn as nn
from torch.nn import functional as F

import ppo.agent
from ppo.agent import AgentValues, NNBase
from ppo.control_flow.env import Action

from ppo.control_flow.recurrence import RecurrentState
import ppo.control_flow.recurrence
import ppo.control_flow.multi_step.abstract_recurrence
import ppo.control_flow.multi_step.no_pointer
import ppo.control_flow.multi_step.oh_et_al
import ppo.control_flow.multi_step.ours
import ppo.control_flow.no_pointer
import ppo.control_flow.oh_et_al
from ppo.distributions import FixedCategorical


class Agent(ppo.agent.Agent, NNBase):
    def __init__(
        self,
        entropy_coef,
        recurrent,
        observation_space,
        no_op_coef,
        baseline,
        **network_args
    ):
        nn.Module.__init__(self)
        self.no_op_coef = no_op_coef
        self.entropy_coef = entropy_coef
        self.multi_step = type(observation_space.spaces["obs"]) is Box
        if not self.multi_step:
            del network_args["conv_hidden_size"]
            del network_args["gate_coef"]
        if baseline == "no-pointer":
            del network_args["gate_coef"]
            self.recurrent_module = (
                ppo.control_flow.multi_step.no_pointer.Recurrence
                if self.multi_step
                else ppo.control_flow.no_pointer.Recurrence
            )(observation_space=observation_space, **network_args)
        elif baseline == "oh-et-al":
            self.recurrent_module = (
                ppo.control_flow.multi_step.oh_et_al.Recurrence
                if self.multi_step
                else ppo.control_flow.oh_et_al.Recurrence
            )(observation_space=observation_space, **network_args)
        elif self.multi_step:
            assert baseline is None
            self.recurrent_module = ppo.control_flow.multi_step.ours.Recurrence(
                observation_space=observation_space, **network_args
            )
        else:
            self.recurrent_module = ppo.control_flow.recurrence.Recurrence(
                observation_space=observation_space, **network_args
            )

    @property
    def recurrent_hidden_state_size(self):
        state_sizes = self.recurrent_module.state_sizes
        state_sizes = state_sizes._replace(P=0)
        return sum(state_sizes)

    @property
    def is_recurrent(self):
        return True

    def forward(self, inputs, rnn_hxs, masks, deterministic=False, action=None):
        N = inputs.size(0)
        all_hxs, last_hx = self._forward_gru(
            inputs.view(N, -1), rnn_hxs, masks, action=action
        )
        rm = self.recurrent_module
        hx = rm.parse_hidden(all_hxs)
        t = type(rm)
        pad = torch.zeros_like(hx.a)
        if t in (
            ppo.control_flow.oh_et_al.Recurrence,
            ppo.control_flow.no_pointer.Recurrence,
        ):
            X = [hx.a, pad, hx.p]
            probs = [hx.a_probs]
        elif t is ppo.control_flow.recurrence.Recurrence:
            X = [hx.a, hx.d, hx.p]
            probs = [hx.a_probs, hx.d_probs]
        elif t is ppo.control_flow.multi_step.no_pointer.Recurrence:
            X = [hx.a, pad, pad, pad, pad]
            probs = [hx.a_probs]
        elif t is ppo.control_flow.multi_step.oh_et_al.Recurrence:
            X = [hx.a, pad, pad, pad, hx.p]
            probs = [hx.a_probs]
        elif t is ppo.control_flow.multi_step.ours.Recurrence:
            X = Action(
                upper=hx.a, lower=hx.ll, delta=hx.d, ag=hx.ag, dg=hx.dg, ptr=hx.p
            )
            ll_type = rm.lower_level_type
            if ll_type == "train-alone":
                probs = Action(
                    upper=None,
                    lower=hx.ll_probs,
                    delta=None,
                    ag=None,
                    dg=None,
                    ptr=None,
                )
            elif ll_type == "train-with-upper":
                probs = Action(
                    upper=hx.a_probs,
                    lower=hx.ll_probs,
                    delta=hx.d_probs,
                    ag=hx.ag_probs,
                    dg=hx.dg_probs,
                    ptr=None,
                )
            elif ll_type in ["pre-trained", "hardcoded"]:
                probs = Action(
                    upper=hx.a_probs,
                    lower=None,
                    delta=hx.d_probs,
                    ag=hx.ag_probs,
                    dg=hx.dg_probs,
                    ptr=None,
                )
            else:
                raise RuntimeError
        else:
            raise RuntimeError
        dists = [(p if p is None else FixedCategorical(p)) for p in probs]
        action_log_probs = sum(
            dist.log_probs(x) for dist, x in zip(dists, X) if dist is not None
        )
        entropy = sum([dist.entropy() for dist in dists if dist is not None]).mean()
        aux_loss = -self.entropy_coef * entropy
        if probs.upper is not None:
            aux_loss += self.no_op_coef * hx.a_probs[:, -1].mean()
        if probs.ag is not None and probs.dg is not None:
            aux_loss += rm.gate_coef * (hx.ag_probs + hx.dg_probs)[:, 1].mean()
        try:
            aux_loss += (rm.gru_gate_coef * hx.gru_gate).mean()
        except AttributeError:
            pass

        action = torch.cat(X, dim=-1)
        test_actions = Action(*action[0, :])
        for field in Action._fields:
            x = getattr(X, field)
            test_action = getattr(test_actions, field)
            assert test_action.item() == x[0].item()

        nlines = len(rm.obs_spaces.lines.nvec)
        P = hx.P.reshape(-1, N, nlines, 2 * nlines, rm.ne)
        rnn_hxs = torch.cat(hx._replace(P=torch.tensor([], device=hx.P.device)), dim=-1)
        return AgentValues(
            value=hx.v,
            action=action,
            action_log_probs=action_log_probs,
            aux_loss=aux_loss,
            dist=None,
            rnn_hxs=rnn_hxs,
            log=dict(entropy=entropy, P=P),
        )

    def _forward_gru(self, x, hxs, masks, action=None):
        if action is None:
            y = F.pad(x, [0, self.recurrent_module.action_size], "constant", -1)
        else:
            y = torch.cat([x, action.float()], dim=-1)
        return super()._forward_gru(y, hxs, masks)

    def get_value(self, inputs, rnn_hxs, masks):
        all_hxs, last_hx = self._forward_gru(
            inputs.view(inputs.size(0), -1), rnn_hxs, masks
        )
        return self.recurrent_module.parse_hidden(last_hx).v
