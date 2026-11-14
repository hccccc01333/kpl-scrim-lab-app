"""Regularized BP lineup interaction study with a forward-time holdout.

The baseline models known team, opponent, patch, side and individual heroes.
The extension adds *observed* own-pair, own-trio and own-vs-enemy features.
No inference is returned when there are too few real games, or when the
interaction model does not improve on a future holdout. Correlation != causation.
"""
from __future__ import annotations
from collections import Counter
from itertools import combinations
from math import exp, log


def _features(g, interaction=False, permitted=None):
    features = ["own:"+h for h in g["picks"]]
    features += ["enemy:"+h for h in g["enemyPicks"]]
    features += ["side:"+str(g["side"]), "team:"+g["team"]]
    if g.get("enemy"):
        features.append("opponent:"+g["enemy"])
    if g.get("version"):
        features.append("version:"+g["version"])
    if interaction:
        own = sorted(g["picks"])
        enemy = sorted(g["enemyPicks"])
        features.extend("pair:"+"|".join(p) for p in combinations(own,2))
        features.extend("trio:"+"|".join(p) for p in combinations(own,3))
        features.extend("counter:"+h+"|"+e for h in own for e in enemy)
    if permitted is not None:
        features = [f for f in features if f in permitted or not
                    (f.startswith("pair:") or f.startswith("trio:") or
                     f.startswith("counter:"))]
    return list(set(features))


def _sigmoid(z):
    if z > 25:
        return 1.0 - 1e-11
    if z < -25:
        return 1e-11
    return 1 / (1 + exp(-z))


def _fit(rows, features, epochs=100):
    """Deterministic full-batch ridge logistic model without extra dependencies."""
    keys = {feature for f in features for feature in f}
    weights = {key:0.0 for key in keys}
    intercept = 0.0
    for epoch in range(epochs):
        grads = {key:0.0 for key in keys}
        g0=0.0
        for g, items in zip(rows, features):
            y = 1.0 if g["result"] else 0.0
            pred = _sigmoid(intercept + sum(weights[x] for x in items))
            error = pred-y
            g0 += error
            for key in items:
                grads[key] += error
        n = len(rows)
        lr = 0.26 if epoch < 50 else 0.14
        intercept -= lr * g0 / n
        for key in keys:
            penalty = 7.0 if key.startswith(("pair:","trio:","counter:")) else 2.0
            weights[key] -= lr*(grads[key]/n+penalty*weights[key]/n)
    return intercept, weights


def _predict(fitted, features):
    bias, weights = fitted
    return _sigmoid(bias + sum(weights.get(x,0.0) for x in features))


def _score(rows, features, fitted):
    if not rows:
        return None
    brier, logloss = 0.0, 0.0
    for g, keys in zip(rows, features):
        actual = 1.0 if g["result"] else 0.0
        p = min(1-1e-9, max(1e-9, _predict(fitted, keys)))
        brier += (p-actual)**2
        logloss += -actual*log(p)-(1-actual)*log(1-p)
    return {"brier":round(brier/len(rows),5),
            "logLoss":round(logloss/len(rows),5)}


def interaction_study(games):
    dated = sorted((g for g in games if g.get("date") and g.get("result") is not None
                    and len(g["picks"])==5 and len(g["enemyPicks"])==5),
                   key=lambda x:(x["date"],x["id"]))
    days=sorted({g["date"] for g in dated})
    summary={"status":"insufficient","train":0,"test":0,
             "baseline":None,"extended":None,"improved":False,
             "signals":[],"reason":"需不少于 40 场、至少 4 个比赛日的已知赛果，且双方阵容完整。"}
    if len(dated)<40 or len(days)<4:
        return summary
    split=days[max(1, int(len(days)*0.7))]
    train=[g for g in dated if g["date"]<split]
    test=[g for g in dated if g["date"]>=split]
    if len(train)<28 or len(test)<10:
        summary["reason"]="时间外训练/测试场次数不足。"
        return summary
    # Gate interaction features exclusively on past training matches.
    support=Counter(key for g in train for key in _features(g,True)
                    if key.startswith(("pair:","trio:","counter:")))
    permitted={key for key,n in support.items()
               if n>=5 and (not key.startswith("trio:") or n>=7)}
    basic_train=[_features(g) for g in train]
    basic_test=[_features(g) for g in test]
    full_train=[_features(g,True,permitted) for g in train]
    full_test=[_features(g,True,permitted) for g in test]
    base=_fit(train,basic_train)
    expanded=_fit(train,full_train)
    base_score=_score(test,basic_test,base)
    expanded_score=_score(test,full_test,expanded)
    improved=(expanded_score["brier"]+0.001 < base_score["brier"] and
              expanded_score["logLoss"] < base_score["logLoss"])
    summary.update({"status":"tested", "train":len(train),"test":len(test),
                    "splitDate":split,"baseline":base_score,"extended":expanded_score,
                    "improved":improved,"reason":("交互模型在未来比赛上同时优于不含交互的基线。"
                         if improved else "交互模型未证明优于单英雄基线；不输出可信协同排序。")})
    if not improved:
        return summary
    weights=expanded[1]
    signs=sorted(((k,v) for k,v in weights.items() if k in permitted),
                 key=lambda x:-abs(x[1]))
    summary["signals"]=[
        {"type":k.split(":")[0],
         "heroes":k.split(":")[1].split("|"),
         "coefficient":round(v,4),"trainGames":support[k],
         "interpretation":("正向额外关联" if v>0 else "负向额外关联")}
        for k,v in signs[:20] if abs(v)>=0.025]
    return summary
