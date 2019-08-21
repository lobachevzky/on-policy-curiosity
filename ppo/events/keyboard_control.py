import argparse
import time

import gym


def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("env", type=gym.make)
    parser.add_argument("seed", type=int)
    run(**vars(parser.parse_args()))


def run(env, actions, seed):
    env.seed(seed)
    actions = list(actions)

    def get_action():
        action = None
        while action not in actions:
            action = input("act:")
            if action == "p":
                import ipdb

                ipdb.set_trace()

        a = actions.index(action)
        unwrapped = env.unwrapped
        if a < len(unwrapped.transitions):
            return a
        i = a - len(unwrapped.transitions)
        touching = [o for o in unwrapped.objects if o.pos == unwrapped.agent.pos]
        try:
            return len(unwrapped.transitions) + unwrapped.object_types.index(
                type(touching[i])
            )
        except IndexError:
            print("out of range")
            return get_action()

    s = env.reset()
    while True:
        env.render(pause=False)
        s, r, t, i = env.step(get_action())
        print("reward", r)
        if t:
            env.render(pause=False)
            print("resetting")
            time.sleep(0.5)
            env.reset()
            print()


if __name__ == "__main__":
    # noinspection PyUnresolvedReferences
    cli()
