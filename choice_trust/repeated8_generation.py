"""One stochastic Qwen draw using the existing joint prompt and parser."""
from __future__ import annotations

from .joint_observation import build_joint_messages, exposed_observation_ids, parse_joint_response, JOINT_PROMPT_VERSION


def generate(entry, *, model, tokenizer, device, config, metadata, seed):
    import torch
    obs = entry['observations']
    messages = build_joint_messages(obs, obs['candidates'])
    if messages != entry['messages']:
        raise ValueError('Frozen joint prompt changed')
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    encoded = tokenizer(prompt, return_tensors='pt', add_special_tokens=False).to(device)
    input_length = int(encoded['input_ids'].shape[-1])
    if input_length > 4096:
        raise ValueError('Prompt exceeds the 4096-token input limit; no truncation')
    kwargs = dict(generation_config=config, use_model_defaults=False, do_sample=True,
                  temperature=0.7, top_p=1.0, top_k=50, num_beams=1,
                  max_new_tokens=512)
    # Transformers 4.57.6 does not accept `generator` as a model.generate kwarg
    # for this checkpoint. The server lock serializes inference; fork_rng restores
    # the CPU RNG after each distinct job seed is applied.
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        with torch.inference_mode():
            output = model.generate(**encoded, **kwargs)
    token_ids = output[0, input_length:].tolist()
    tokens = output[0, input_length:]
    raw = tokenizer.decode(tokens, skip_special_tokens=True)
    full = tokenizer.decode(tokens, skip_special_tokens=False)
    eos = config.eos_token_id
    eos_ids = {eos} if isinstance(eos, int) else set(eos or [])
    truncated = False if token_ids and token_ids[-1] in eos_ids else True if len(token_ids) >= 512 else None
    parsed, diagnostics = parse_joint_response(raw, obs['candidates'], obs, truncated=truncated)
    return {'prompt_version': JOINT_PROMPT_VERSION, 'observation_version': obs['version'],
            'messages': messages, 'rendered_prompt': prompt,
            'included_observation_ids': exposed_observation_ids(obs),
            'raw_response': raw, 'raw_response_with_special_tokens': full,
            'raw_output_token_ids': token_ids, 'parsed_result': parsed,
            'diagnostics': diagnostics,
            'generation_metadata': {'model': metadata, 'effective_settings':
                {'do_sample': True, 'temperature': 0.7, 'top_p': 1.0, 'top_k': 50,
                 'num_beams': 1, 'max_new_tokens': 512, 'use_model_defaults': False,
                 'enable_thinking': False, 'max_input_tokens': 4096,
                 'eos_token_id': eos, 'pad_token_id': config.pad_token_id,
                 'use_cache': config.use_cache}, 'seed': seed, 'input_tokens': input_length,
                'output_tokens': len(token_ids), 'finish_reason':
                    'stop' if truncated is False else 'length' if truncated else 'unknown',
                'seed_application': 'torch.random.fork_rng(devices=[]) + torch.manual_seed(seed) under server inference lock',
                'actual_generate_kwargs': {k: v for k, v in kwargs.items() if k != 'generation_config'}}}
