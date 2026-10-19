"""Pure helpers shared by server and tests. No Torch dependency here."""
import math


def answer_labels(candidate_ids):
    # Stable mapping independent of presentation order. Spreadsheet-style labels.
    def label(n):
        result = ''
        while n:
            n, rem = divmod(n-1,26)
            result = chr(65+rem)+result
        return result
    return {cid:label(i+1) for i,cid in enumerate(sorted(candidate_ids))}


def contextual_tokens(tokenizer, rendered, prefix_ids, answers):
    if not answers or len(set(answers.values())) != len(answers):
        raise ValueError('Answer strings must be nonempty and unique')
    result={}
    for cid, answer in answers.items():
        if not isinstance(answer,str) or not answer or len(answer)>128:
            raise ValueError('Invalid answer label')
        extended=tokenizer.encode(rendered+answer,add_special_tokens=False)
        if extended[:len(prefix_ids)]!=prefix_ids or len(extended)==len(prefix_ids):
            raise ValueError(f'Answer label for {cid} changes the prompt token boundary')
        result[cid]=extended[len(prefix_ids):]
    sequences=list(result.values())
    if len(set(map(tuple,sequences)))!=len(sequences): raise ValueError('Token sequence collision')
    # Prefixes (A vs AA) are valid strings but not disjoint answer events. Reject
    # them rather than pretending prefix probabilities are comparable. A newline
    # terminator makes the generated >26-label scheme prefix-free.
    if any(a==b[:len(a)] for i,a in enumerate(sequences) for j,b in enumerate(sequences) if i!=j):
        raise ValueError('Answer token sequences must be prefix-free; add a terminator')
    return result


def normalize_log_scores(log_scores):
    if not log_scores or any(not math.isfinite(x) for x in log_scores.values()):
        raise ValueError('Nonfinite candidate sequence log scores')
    m=max(log_scores.values())
    exps={k:math.exp(v-m) for k,v in log_scores.items()}
    return {k:v/sum(exps.values()) for k,v in exps.items()}


def autoregressive_log_score(prefix, suffix, next_log_probability):
    """Sum log p(token | prompt, previous answer tokens); no length averaging."""
    context=list(prefix)
    total=0.0
    for token in suffix:
        total+=float(next_log_probability(context,token))
        context.append(token)
    return total


def validate_prediction(result, ids):
    if result.get('prediction') not in ids:
        raise ValueError('Backend prediction does not map to a candidate ID')
    scores=result.get('scores')
    if scores is not None:
        if set(scores)!=set(ids) or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 or v>1 for v in scores.values()):
            raise ValueError('Invalid candidate scores')
        if abs(sum(scores.values())-1)>1e-5: raise ValueError('Normalized scores must sum to one')
        if scores[result['prediction']] < max(scores.values())-1e-7:
            raise ValueError('Prediction is inconsistent with maximum score')
    return result
