# stdlib
import time
from pathlib import Path
from typing import Dict

import numpy as np
import torch
from rl_utils import hierarchical_parse_args
from tensorboardX import SummaryWriter

# noinspection PyUnresolvedReferences
# first party
import gridworld_env
from hsr.util import env_wrapper
from ppo.arguments import get_args, get_hsr_args, build_parser
from ppo.envs import make_vec_envs, VecNormalize
from ppo.policy import Policy
from ppo.storage import RolloutStorage
from ppo.update import PPO


# third party


def main(num_frames, num_steps, num_processes, seed,
         cuda_deterministic, cuda, log_dir: Path, env_id, gamma, normalize,
         add_timestep, save_interval, save_dir, log_interval, eval_interval,
         use_gae, tau, ppo_args, env_args, network_args, render, load_path):
    if render:
        num_processes = 1

    num_updates = int(num_frames) // num_steps // num_processes

    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)

    if cuda and torch.cuda.is_available() and cuda_deterministic:
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True

    eval_log_dir = None
    if log_dir:
        writer = SummaryWriter(log_dir=str(log_dir))
        eval_log_dir = log_dir.joinpath("eval")

        for _dir in [log_dir, eval_log_dir]:
            try:
                _dir.mkdir()
            except OSError:
                for f in _dir.glob('*.monitor.csv'):
                    f.unlink()

    torch.set_num_threads(1)
    device = torch.device("cuda:0" if cuda else "cpu")

    _gamma = gamma if normalize else None
    envs = make_vec_envs(env_id, seed, num_processes, _gamma, log_dir,
                         add_timestep, device, False, env_args, render)

    actor_critic = Policy(
        envs.observation_space.shape,
        envs.action_space,
        **network_args)
    actor_critic.to(device)

    agent = PPO(actor_critic=actor_critic, **ppo_args)

    rollouts = RolloutStorage(
        num_steps=num_steps,
        num_processes=num_processes,
        obs_shape=envs.observation_space.shape,
        action_space=envs.action_space,
        recurrent_hidden_state_size=actor_critic.recurrent_hidden_state_size,
    )

    obs = envs.reset()
    rollouts.obs[0].copy_(obs)
    rollouts.to(device)

    rewards_counter = np.zeros(num_processes)
    time_step_counter = np.zeros(num_processes)
    episode_rewards = []
    time_steps = []

    start = time.time()
    last_save = start

    if load_path:
        state_dict = torch.load(load_path)
        actor_critic.load_state_dict(state_dict['actor_critic'])
        agent.optimizer.load_state_dict(state_dict['optimizer'])
        start = state_dict.get('step', -1) + 1
        if isinstance(envs.venv, VecNormalize):
            envs.venv.load_state_dict(state_dict['vec_normalize'])
        print(f'Loaded parameters from {load_path}.')

    for j in range(num_updates):
        for step in range(num_steps):
            # Sample actions.add_argument_group('env_args')
            with torch.no_grad():
                value, action, action_log_prob, recurrent_hidden_states = \
                    actor_critic.act(
                        rollouts.obs[step], rollouts.recurrent_hidden_states[step],
                        rollouts.masks[step])

            # Observe reward and next obs
            obs, reward, done, infos = envs.step(action)

            # track rewards
            rewards_counter += reward.numpy()
            time_step_counter += 1
            episode_rewards.append(rewards_counter[done])
            time_steps.append(time_step_counter[done])
            rewards_counter[done] = 0
            time_step_counter[done] = 0

            # If done then clean the history of observations.
            masks = torch.FloatTensor(
                [[0.0] if done_ else [1.0] for done_ in done])
            rollouts.insert(obs, recurrent_hidden_states, action,
                            action_log_prob, value, reward, masks)

        with torch.no_grad():
            next_value = actor_critic.get_value(
                rollouts.obs[-1], rollouts.recurrent_hidden_states[-1],
                rollouts.masks[-1]).detach()

        rollouts.compute_returns(next_value, use_gae, gamma, tau)
        train_results = agent.update(rollouts)
        rollouts.after_update()

        if log_dir and save_interval and \
                time.time() - last_save >= save_interval:
            last_save = time.time()
            modules = dict(
                optimizer=agent.optimizer,
                actor_critic=actor_critic)  # type: Dict[str, torch.nn.Module]

            if isinstance(envs.venv, VecNormalize):
                modules.update(vec_normalize=envs.venv)

            state_dict = {
                name: module.state_dict()
                for name, module in modules.items()
            }
            save_path = Path(log_dir, 'checkpoint.pt')
            torch.save(dict(step=j, **state_dict), save_path)

            print(f'Saved parameters to {save_path}')

        total_num_steps = (j + 1) * num_processes * num_steps

        if j % log_interval == 0:
            end = time.time()
            fps = int(total_num_steps / (end - start))
            episode_rewards = np.concatenate(episode_rewards)
            if episode_rewards.size > 0:
                print(
                    f"Updates {j}, num timesteps {total_num_steps}, FPS {fps} \n "
                    f"Last {len(episode_rewards)} training episodes: " +
                    "mean/median reward {:.2f}/{:.2f}, min/max reward {:.2f}/{"
                    ":.2f}\n".format(
                        np.mean(episode_rewards), np.median(episode_rewards),
                        np.min(episode_rewards), np.max(episode_rewards)))
            if log_dir:
                writer.add_scalar('return', np.mean(episode_rewards), j)
                for k, v in train_results.items():
                    if log_dir and np.isscalar(v):
                        writer.add_scalar(k.replace('_', ' '), v, j)
            episode_rewards = []

        if eval_interval is not None and j % eval_interval == eval_interval - 1:
            eval_envs = make_vec_envs(
                env_id,
                seed + num_processes,
                num_processes,
                _gamma,
                eval_log_dir,
                add_timestep,
                device,
                env_args=env_args,
                render=render,
                allow_early_resets=True)

            # vec_norm = get_vec_normalize(eval_envs)
            # if vec_norm is not None:
            #     vec_norm.eval()
            #     vec_norm.ob_rms = get_vec_normalize(envs).ob_rms

            eval_episode_rewards = []

            obs = eval_envs.reset()
            eval_recurrent_hidden_states = torch.zeros(
                num_processes,
                actor_critic.recurrent_hidden_state_size,
                device=device)
            eval_masks = torch.zeros(num_processes, 1, device=device)

            while len(eval_episode_rewards) < 10:
                with torch.no_grad():
                    _, action, _, eval_recurrent_hidden_states = actor_critic.act(
                        obs,
                        eval_recurrent_hidden_states,
                        eval_masks,
                        deterministic=True)

                # Observe reward and next obs
                obs, reward, done, infos = eval_envs.step(action)

                eval_masks = torch.FloatTensor(
                    [[0.0] if done_ else [1.0] for done_ in done])
                for info in infos:
                    if 'episode' in info.keys():
                        eval_episode_rewards.append(info['episode']['r'])

            eval_envs.close()

            print(" Evaluation using {} episodes: mean reward {:.5f}\n".format(
                len(eval_episode_rewards), np.mean(eval_episode_rewards)))


def cli():
    main(**get_args())


def logic_cli():
    parser = build_parser()
    parser.add_argument_group('env_args')

    def _main(env_id, env_args, network_args, **kwargs):
        env_args.update(gridworld_env.get_args(env_id))
        del env_args['env_id']
        del env_args['class']
        network_args.update(logic=True)
        main(env_id=env_id, env_args=env_args,
             network_args=network_args, **kwargs)

    _main(**hierarchical_parse_args(parser))


def hsr_cli():
    args = get_hsr_args()
    env_wrapper(main)(**args)


if __name__ == "__main__":
    logic_cli()
