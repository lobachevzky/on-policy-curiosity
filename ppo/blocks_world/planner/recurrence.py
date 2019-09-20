from collections import namedtuple

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn as nn

from ppo.distributions import Categorical, FixedCategorical
from ppo.layers import Flatten
from ppo.mdp.env import Obs
from ppo.utils import init_

RecurrentState = namedtuple("RecurrentState", "a probs planned_probs plan v t state h")
XiSections = namedtuple("XiSections", "Kr Br kw bw e v F_hat ga gw Pi")


def batch_conv1d(inputs, weights):
    outputs = []
    # one convolution per instance
    n = inputs.shape[0]
    for i in range(n):
        x = inputs[i]
        w = weights[i]
        convolved = F.conv1d(x.reshape(1, 1, -1), w.reshape(1, 1, -1), padding=2)
        outputs.append(convolved.squeeze(0))
    padded = torch.cat(outputs)
    padded[:, 1] = padded[:, 1] + padded[:, 0]
    padded[:, -2] = padded[:, -2] + padded[:, -1]
    return padded[:, 1:-1]


class Recurrence(nn.Module):
    def __init__(
        self,
        observation_space,
        action_space,
        activation,
        hidden_size,
        num_layers,
        debug,
        num_slots,
        slot_size,
        embedding_size,
        num_heads,
        planning_steps,
        num_model_layers,
        num_embedding_layers,
    ):
        super().__init__()
        self.planning_steps = planning_steps
        self.action_size = 1 + planning_steps
        self.debug = debug
        self.slot_size = slot_size
        self.num_slots = num_slots
        self.num_heads = num_heads
        nvec = observation_space.nvec
        self.obs_shape = (*nvec.shape, nvec.max())
        self.num_options = nvec.max()
        self.hidden_size = hidden_size

        self.state_sizes = RecurrentState(
            a=1,
            plan=planning_steps,
            v=1,
            t=1,
            probs=action_space.nvec.max(),
            planned_probs=planning_steps * action_space.nvec.max(),
            state=embedding_size,
            h=hidden_size * num_model_layers,
        )
        self.xi_sections = XiSections(
            Kr=num_heads * slot_size,
            Br=num_heads,
            kw=slot_size,
            bw=1,
            e=slot_size,
            v=slot_size,
            F_hat=num_heads,
            ga=1,
            gw=1,
            Pi=3 * num_heads,
        )

        # networks
        assert num_layers > 0
        self.embed_action = nn.Embedding(
            int(action_space.nvec.max()), int(action_space.nvec.max())
        )
        layers = [nn.Embedding(nvec.max(), nvec.max()), Flatten()]
        in_size = int(nvec.max() * np.prod(nvec.shape))
        for _ in range(num_embedding_layers):
            layers += [activation, init_(nn.Linear(in_size, hidden_size))]
            in_size = hidden_size
        self.embed1 = nn.Sequential(*layers)
        self.embed2 = nn.Sequential(
            activation, init_(nn.Linear(hidden_size, embedding_size))
        )
        self.model = nn.GRU(
            embedding_size + self.embed_action.embedding_dim,
            hidden_size,
            num_model_layers,
        )
        self.actor = Categorical(embedding_size, action_space.nvec.max())
        self.critic = init_(nn.Linear(embedding_size, 1))
        self.register_buffer("mem_one_hots", torch.eye(num_slots))

    @staticmethod
    def sample_new(x, dist):
        new = x < 0
        x[new] = dist.sample()[new].flatten()

    def forward(self, inputs, hx):
        return self.pack(self.inner_loop(inputs, rnn_hxs=hx))

    def pack(self, hxs):
        def pack():
            for name, size, hx in zip(
                RecurrentState._fields, self.state_sizes, zip(*hxs)
            ):
                x = torch.stack(hx).float()
                assert np.prod(x.shape[2:]) == size
                yield x.view(*x.shape[:2], -1)

        hx = torch.cat(list(pack()), dim=-1)
        return hx, hx[-1:]

    def parse_inputs(self, inputs: torch.Tensor):
        return Obs(*torch.split(inputs, self.obs_sections, dim=-1))

    def parse_hidden(self, hx: torch.Tensor) -> RecurrentState:
        return RecurrentState(*torch.split(hx, self.state_sizes, dim=-1))

    def print(self, t, *args, **kwargs):
        if self.debug:
            if type(t) == torch.Tensor:
                t = (t * 10.0).round() / 10.0
            print(t, *args, **kwargs)

    def inner_loop(self, inputs, rnn_hxs):
        device = inputs.device
        T, N, D = inputs.shape
        inputs, actions = torch.split(
            inputs.detach(), [D - self.action_size, self.action_size], dim=2
        )
        inputs = inputs.long()

        hx = self.parse_hidden(rnn_hxs)
        for _x in hx:
            _x.squeeze_(0)

        plan = hx.plan
        planned_probs = hx.planned_probs.view(N, self.planning_steps, -1)

        new = torch.all(rnn_hxs == 0, dim=-1)
        if new.any():
            assert new.all()
            state = self.embed2(self.embed1(inputs[0]))
        else:
            state = hx.state.view(N, -1)

        h = (
            hx.h.view(N, self.model.num_layers, self.model.hidden_size)
            .transpose(0, 1)
            .contiguous()
        )

        A = actions.long()[:, :, 0]

        for t in range(T):
            state = self.embed2(self.embed1(inputs[t]))
            dist = self.actor(state)
            value = self.critic(state)
            self.sample_new(A[t], dist)
            model_input = torch.cat([state, self.embed_action(A[t])], dim=-1)
            # hn, h = self.model(model_input.unsqueeze(0), h)
            # state = self.embed2(hn.squeeze(0))
            yield RecurrentState(
                a=A[t],
                plan=plan,
                planned_probs=planned_probs,
                probs=dist.probs,
                v=value,
                t=hx.t + 1,
                state=hx.state,
                h=h.transpose(0, 1),
            )
