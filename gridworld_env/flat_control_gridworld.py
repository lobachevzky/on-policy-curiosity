from collections import Counter, OrderedDict, namedtuple

from gym import spaces
import numpy as np

from dataclasses import dataclass
import gridworld_env
from gridworld_env import SubtasksGridWorld
from gridworld_env.subtasks_gridworld import Obs


class Else:
    def __str__(self):
        return "else:"


class EndIf:
    def __str__(self):
        return "endif"


class FlatControlFlowGridWorld(SubtasksGridWorld):
    def __init__(self, *args, n_subtasks, **kwargs):
        n_subtasks += 1
        super().__init__(*args, n_subtasks=n_subtasks, **kwargs)
        self.passing_prob = 0.5
        self.pred = None
        self.force_branching = False

        self.conditions = None
        self.control = None
        self.required_objects = None
        obs_spaces = self.observation_space.spaces
        subtask_nvec = obs_spaces["subtasks"].nvec[0]
        self.lines = None
        self.required_objects = None
        # noinspection PyProtectedMember
        self.n_lines = self.n_subtasks + self.n_subtasks // 2 - 1
        self.observation_space.spaces.update(
            subtask=spaces.Discrete(self.observation_space.spaces["subtask"].n + 1),
            subtasks=spaces.MultiDiscrete(
                np.tile(
                    np.pad(
                        subtask_nvec,
                        [0, 1],
                        "constant",
                        constant_values=1 + len(self.object_types),
                    ),
                    (self.n_lines, 1),
                )
            ),
        )
        world = self

        @dataclass
        class If:
            obj: int

            def __str__(self):
                return f"if {world.object_types[self.obj]}:"

        self.If = If

    def task_string(self):
        print("object_types")
        print(self.object_types)
        print("conditions")
        print(self.conditions)
        print("control")
        print(self.control)
        print("one-step", self.one_step)
        print("branching", self.branching)

        def helper(i, indent):
            try:
                subtask = f"{i}:{self.subtasks[i]}"
            except IndexError:
                return f"{indent}terminate"
            neg, pos = self.control[i]
            condition = self.conditions[i]

            # def develop_branch(j, add_indent):
            # new_indent = indent + add_indent
            # try:
            # subtask = f"{j}:{self.subtasks[j]}"
            # except IndexError:
            # return f"{new_indent}terminate"
            # return f"{new_indent}{subtask}\n{helper(j, new_indent)}"

            if pos == neg:
                if_condition = helper(pos, indent)
            else:
                if_condition = f"""\
{indent}if {self.object_types[condition]}:
{helper(pos, indent + '    ')}
{indent}else:
{helper(neg, indent + '    ')}
"""
            return f"{indent}{subtask}\n{if_condition}"

        return helper(i=0, indent="")

    # def task_string(self):
    #     lines = iter(self.lines)
    #
    #     def helper():
    #         while True:
    #             line = next(lines, None)
    #             if line is None:
    #                 return
    #             if isinstance(line, self.Subtask):
    #                 yield str(line)
    #             elif isinstance(line, self.If):
    #                 yield str(line)
    #                 yield f"    {next(lines)}"
    #
    #     return "\n".join(helper())

    def get_control(self):
        for i in range(self.n_subtasks):
            if i % 3 == 0:
                if not self.one_step or self.branching:
                    yield i + 1, i
                else:
                    yield i, i
            elif i % 3 == 1:
                yield i, i
            elif i % 3 == 2:
                yield i + 1, i + 1  # terminate

    def reset(self):
        self.subtask_idx = None
        self.one_step = self.np_random.rand() < 0.5
        self.branching = self.np_random.rand() < 0.5

        self.control = np.minimum(
            1 + np.array(list(self.get_control())), self.n_subtasks
        )
        object_types = np.arange(len(self.object_types))
        existing = self.np_random.choice(
            object_types, size=len(self.object_types) // 2, replace=False
        )
        non_existing = np.array(list(set(object_types) - set(existing)))
        n_passing = self.np_random.choice(
            2, p=[1 - self.passing_prob, self.passing_prob], size=self.n_subtasks
        ).sum()
        passing = self.np_random.choice(existing, size=n_passing)
        failing = self.np_random.choice(non_existing, size=self.n_subtasks - n_passing)
        self.conditions = np.concatenate([passing, failing])
        self.np_random.shuffle(self.conditions)
        self.required_objects = []
        if self.one_step:
            if self.branching:
                self.conditions[0] = self.np_random.choice(existing)
                self.required_objects = [self.conditions[0]]
            else:
                self.conditions[0] = self.np_random.choice(non_existing)
        else:
            self.conditions[0] = self.np_random.choice(non_existing)
        self.passing = self.conditions[0] in passing

        self.pred = False
        self.subtasks = list(self.subtasks_generator())

        def get_lines():
            for subtask, (pos, neg), condition in zip(
                self.subtasks, self.control, self.conditions
            ):
                yield subtask
                if pos != neg:
                    yield self.If(condition)

        self.lines = list(get_lines())[1:]
        return super().reset()

    def step(self, action):
        s, r, t, i = super().step(action)
        i.update(passing=self.passing)
        return s, r, t, i

    def get_observation(self):
        obs = super().get_observation()

        def get_lines():
            for line in self.lines:
                if isinstance(line, self.Subtask):
                    yield line + (0,)
                elif isinstance(line, self.If):
                    yield (0, 0, 0) + (1 + line.obj,)
                else:
                    raise NotImplementedError

        lines = np.pad(
            list(get_lines()), [(0, self.n_lines - len(self.lines)), (0, 0)], "constant"
        )
        obs.update(subtasks=lines)
        for (k, s) in self.observation_space.spaces.items():
            assert s.contains(obs[k])
        return OrderedDict(obs)

    def subtasks_generator(self):
        interactions = list(range(len(self.interactions)))
        self.irreversible_interactions = irreversible_interactions = [
            j for j, i in enumerate(self.interactions) if i in ("pick-up", "transform")
        ]

        object_types = np.arange(len(self.object_types))
        non_existing = [self.np_random.choice(object_types)]
        self.existing = existing = list(set(object_types) - set(non_existing))
        self.lines = []
        one_step = False

        # noinspection PyTypeChecker
        for i in range(self.n_subtasks):
            if not one_step and i == self.n_subtasks - 1:
                one_step = True
            else:
                one_step = self.np_random.rand() < 0.5
            subtask_obj = self.np_random.choice(existing)
            self.np_random.shuffle(irreversible_interactions)
            passing_interaction, failing_interaction = (
                irreversible_interactions
                if i == 1
                else self.np_random.choice(interactions, size=2)
            )
            if one_step:
                branching = self.np_random.rand() < 0.5
                if branching:
                    condition_obj = self.np_random.choice(existing)
                    yield self.If(condition_obj)
                    yield self.Subtask(
                        interaction=passing_interaction, count=0, object=subtask_obj
                    )

                else:  # not branching but still one-step
                    subtask_interaction = self.np_random.choice(interactions)
                    yield self.Subtask(
                        interaction=subtask_interaction, count=0, object=subtask_obj
                    )
            else:  # two-step
                yield self.If(self.np_random.choice(non_existing))
                yield self.Subtask(
                    interaction=failing_interaction, count=0, object=subtask_obj
                )
        if not self.branching:
            choices = self.np_random.choice(
                len(self.possible_subtasks), size=self.n_subtasks
            )
            for i in choices:
                yield self.Subtask(*self.possible_subtasks[i])
            return

    def get_required_objects(self, subtasks):
        available = []
        passing = True
        for line in subtasks:
            if isinstance(line, self.If):
                passing = line.obj in self.existing
                if passing and line.obj not in available:
                    available += [line.obj]
                    yield line.obj
            if passing and isinstance(line, self.Subtask):
                if line.object not in available:
                    self.required_objects += [line.object]
                    if line.interaction not in self.irreversible_interactions:
                        yield line.object

    @property
    def subtask(self):
        try:
            return self.lines[self.subtask_idx]
        except IndexError:
            return

    def get_next_subtask(self):
        if self.subtask_idx is None:
            i = 0
        else:
            i = self.subtask_idx + 1
        while True:
            if i >= len(self.lines):
                return i
            line = self.lines[i]
            if isinstance(line, self.Subtask):
                return i
            elif isinstance(line, self.If):
                if line.obj in self.objects.values():
                    i += 1
                else:
                    i += 2

    def evaluate_condition(self):
        self.pred = self.conditions[self.subtask_idx] in self.objects.values()
        return self.pred


def main(seed, n_subtasks):
    kwargs = gridworld_env.get_args("4x4SubtasksGridWorld-v0")
    del kwargs["class_"]
    del kwargs["max_episode_steps"]
    kwargs.update(n_subtasks=n_subtasks, max_task_count=1)
    env = FlatControlFlowGridWorld(**kwargs, evaluation=False, eval_subtasks=[])
    actions = "wsadeq"
    gridworld_env.keyboard_control.run(env, actions=actions, seed=seed)


if __name__ == "__main__":
    import argparse
    import gridworld_env.keyboard_control

    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-subtasks", type=int, default=5)
    main(**vars(parser.parse_args()))
