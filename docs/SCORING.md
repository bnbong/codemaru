[English](#how-a-codemaru-tier-is-computed) · [한국어](#codemaru-티어-산정-방식)

# How a codemaru tier is computed

This is a from-scratch walkthrough of the scoring pipeline, using a real profile (`bnbong`) as the example. 

Numbers are a point-in-time snapshot (`scoreVersion` 0.4.0) and change with live data.

> Scores summarize **public activity**, not an absolute skill rating.

## The pipeline

```
raw platform data  →  5 axis scores  →  overall  ─┐
                                                  ├─→  tier = min(score-tier, confidence-cap)
data completeness  →  confidence      →  cap  ────┘
```

1. Each **axis** is a weighted average of a few **signals** (raw counts).
2. The five axes blend into one **overall** score (0–100).
3. **Confidence** (0–1) measures how much *verifiable* data we have it never appears on the card but **caps** the maximum tier.
4. The final **tier** is the lower of the score-based tier and the confidence cap.

Before the example, two building blocks explain the "magic" arrows like `386 → 78.4`.

## Building block 1 — turning a raw number into a 0–100 score

A raw count (386 commits, 72 stars, …) can't be used directly: it's unbounded, so each raw value is squashed onto a 0–100 scale with **diminishing returns**, using one of two functions.

**`logScore`** (for unbounded counts — commits, stars, solved problems):

$$\mathrm{logScore}(v,s) = \min\left(100, \frac{\ln(1+v)}{\ln(1+s)}\times 100\right)$$

- $v$ = the raw value, $s$ = the **saturation** (the value at which the score reaches ~100). A larger $s$ means the score grows more slowly.
- Worked example — commits, with saturation $s = 2000$:

$$\mathrm{logScore}(386,2000)=\frac{\ln(387)}{\ln(2001)}\times 100=\frac{5.96}{7.60}\times 100\approx \mathbf{78.4}$$

  That is the `386 → 78.4` step: 386 commits, normalized with a saturation of 2000, is worth **78.4 out of 100**.

**`linScore`** (for values that already have a natural maximum — e.g. active days out of 365):

$$\mathrm{linScore}(v,m) = \min\left(100, \frac{v}{m}\times 100\right)$$

  e.g. 127 active days out of $m = 365$ → $\frac{127}{365}\times100 \approx 34.8$.

## Building block 2 — combining signals into an axis

Each axis takes several normalized signals and averages them by importance (**weights**). 

For signals $s_i$ with weights $w_i$:

$$\text{axis} = \frac{\sum_i s_i \times w_i}{\sum_i w_i}$$

> **Notation:** `×` always means **multiply**. In the tables below, each signal
> is its own row the **contribution** column is simply `score × weight`. The
> axis score is the sum of the contributions (the weights here add up to 1, so
> there's no extra division).

The five axes and their weights in the final blend:

| Axis | Signals (source) | Weight in overall |
| --- | --- | --- |
| Open Source | commits, contributed repos, PRs, reviews, issues — past year (GitHub) | 0.30 |
| Problem Solving | total problems solved, summed across judges (solved.ac + LeetCode + JungOl) | 0.20 |
| Depth | algorithmic depth (judges) **or** a standout owned project, + language breadth | 0.20 |
| Consistency | active days, longest streak (GitHub) | 0.15 |
| Impact | stars, forks, followers, public repos (GitHub) | 0.15 |

## Worked example — `bnbong`

Inputs: GitHub `bnbong`, solved.ac `bnbong`, LeetCode `bnbong`.

### Open Source (axis weight 0.30)

| Signal | Raw | Normalized (`logScore`, saturation) | Weight | Contribution (score × weight) |
| --- | --- | --- | --- | --- |
| commits | 386 | 78.4 ($s=2000$) | 0.40 | 31.4 |
| contributed repos | 13 | 64.2 ($s=60$) | 0.20 | 12.8 |
| PRs | 44 | 71.8 ($s=200$) | 0.15 | 10.8 |
| reviews | 0 | 0.0 ($s=150$) | 0.15 | 0.0 |
| issues | 29 | 67.8 ($s=150$) | 0.10 | 6.8 |

$$\text{OpenSource}=31.4+12.8+10.8+0.0+6.8=\mathbf{61.8}$$

### Impact (axis weight 0.15)

| Signal | Raw | Normalized (`logScore`, saturation) | Weight | Contribution |
| --- | --- | --- | --- | --- |
| stars | 72 | 53.6 ($s=3000$) | 0.45 | 24.1 |
| forks | 9 | 34.4 ($s=800$) | 0.20 | 6.9 |
| followers | 64 | 57.1 ($s=1500$) | 0.20 | 11.4 |
| public repos | 43 | 86.1 ($s=80$) | 0.15 | 12.9 |

$$\text{Impact}=24.1+6.9+11.4+12.9=\mathbf{55.3}$$

### Consistency (axis weight 0.15)

Uses `linScore` (these values have a natural maximum):

| Signal | Raw | Normalized (`linScore`, max) | Weight | Contribution |
| --- | --- | --- | --- | --- |
| active days | 127 | 34.8 ($m=365$) | 0.60 | 20.9 |
| longest streak | 6 | 5.0 ($m=120$) | 0.40 | 2.0 |

$$\text{Consistency}=20.9+2.0=\mathbf{22.9}$$

### Problem Solving (axis weight 0.20)

Solved counts are **summed across all judges first**, then normalized once — so linking another judge can only raise the score, never dilute it:

$$\text{ProblemSolving}=\mathrm{logScore}(\underbrace{229}_{\text{BOJ}}+\underbrace{2}_{\text{LeetCode}},2500)=\mathrm{logScore}(231,2500)\approx\mathbf{69.6}$$

### Depth (axis weight 0.20)

Depth is the **deeper of two pillars**, plus a small breadth bonus. Each pillar is itself a weighted average.

**Pillar A — algorithmic depth** ($P_{\text{algo}}$):

| Signal | Raw | Normalized | Weight | Contribution |
| --- | --- | --- | --- | --- |
| BOJ tier | 12 | 40.0 (`linScore`, $m=30$) | 0.50 | 20.0 |
| hard-weighted solves | 3.0 | 23.1 (`logScore`, $s=400$) | 0.50 | 11.6 |

$$P_{\text{algo}}=20.0+11.6=\mathbf{31.6}$$

(*hard-weighted solves* counts harder problems more: gold ×0.3, platinum ×1, diamond ×2, ruby ×3. bnbong has 10 gold → $10\times0.3=3.0$.)

**Pillar B — representative project** ($P_{\text{project}}$, the single most-starred *owned* repo):

| Signal | Raw | Normalized (`logScore`, saturation) | Weight | Contribution |
| --- | --- | --- | --- | --- |
| top repo stars | 50 | 39.7 ($s=20000$) | 0.75 | 29.8 |
| top repo forks | 4 | 18.9 ($s=5000$) | 0.25 | 4.7 |

$$P_{\text{project}}=29.8+4.7=\mathbf{34.5}$$

**Breadth bonus** — language count, normalized: $\mathrm{logScore}(12,12)=100$.

The two pillars combine as a **max** (either alone can reach 100), and breadth only fills the *leftover headroom* (at most +15%), so a weak signal never drags a strong one down:

$$\text{primary}=\max(P_{\text{algo}},P_{\text{project}})=\max(31.6,34.5)=34.5$$

$$\text{Depth}=\text{primary}+(100-\text{primary})\times 0.15\times\frac{\text{breadth}}{100}=34.5+(100-34.5)\times 0.15\times 1.0\approx\mathbf{44.3}$$

### Overall

Blend the five axes by their weights:

$$\text{overall}=0.30O+0.20P+0.20D+0.15C+0.15I$$

$$=0.30(61.8)+0.20(69.6)+0.20(44.3)+0.15(22.9)+0.15(55.3)=\mathbf{53.0}$$

### Confidence and the tier cap

Confidence asks "*how much trustworthy data do we actually have?*" Each platform contributes a factor scaled by its **data volume** (not mere presence), so a brand-new account adds almost nothing.

For a judge, the factor uses a small "free" threshold of 10 solves — the first handful of solves count as zero, so an empty account can't inflate the tier:

$$f_{\text{judge}}=\text{trust}\times\frac{\mathrm{logScore}\big(\max(0, \text{solved}-10), s\big)}{100}$$

- GitHub factor — the **stronger of** recent activity *or* a standout owned project (for bnbong, recent activity dominates): $f_{\text{gh}} = 0.979$
- solved.ac factor: trust $1.0$, $\mathrm{logScore}(229-10,2200)/100 \Rightarrow f_{\text{solvedac}} = 0.701$
- LeetCode factor: only 2 solves, and $\max(0,2-10)=0$, so $f_{\text{leetcode}} = 0$
- JungOl factor: no handle supplied, so the term is simply absent

$$\text{confidence}=0.6f_{\text{gh}}+0.25f_{\text{solvedac}}+0.15f_{\text{leetcode}}+0.10f_{\text{jungol}}=0.6(0.979)+0.25(0.701)+0+0=\mathbf{0.763}$$

Judge weights are **added**, never renormalized: a judge that ships later cannot
lower an existing confidence, and the existing clamp to $[0,1]$ absorbs the fact
that the weights now sum past 1.

A confidence of **0.763** opens the cap up to **Master**.

### Final tier

$$\text{tier}=\min(\underbrace{\text{Gold}}_{\text{score }53.0\in[45,58)}, \underbrace{\text{Master}}_{\text{confidence cap}})=\textbf{Gold}$$

The overall score (53.0) lands in the Gold band, and the confidence cap (Master) is higher, so it doesn't pull the tier down. **bnbong → Gold.**

## Confidence, caps, and Maru

- Confidence scales with *verifiable solve volume / activity*, not platform count — linking a brand-new account with a handful of solves adds ~nothing.
- GitHub confidence also credits a **standout owned project**, so a historically significant flagship isn't capped low just for being recently quiet.
- A strong **single-source** profile (e.g. GitHub-only) can reach up to **Master**.
- The top tier **Maru** is reserved for an all-round, multi-platform *pentagon*: deep across both open-source and algorithm activity.

## Where each judge fits

All judges feed the same two axes, and always **additively**:

| Judge | Problem Solving | Depth | trust | saturation | confidence weight |
| --- | --- | --- | --- | --- | --- |
| solved.ac / BOJ | solved count | tier (`linScore`, $m=30$) + hard volume | 1.00 | 2200 | 0.25 |
| LeetCode | solved count | contest rating above 1200 + hard solves | 0.75 | 1400 | 0.15 |
| JungOl | solved count | tier × **0.80** + hard volume | 0.60 | 900 | 0.10 |

JungOl uses the same 0–30 tier scale as solved.ac (its own site states that tiers
are computed from a solved.ac AC rating), so the difficulty bands and tier names
carry over unchanged. Its problem pool is far smaller than BOJ's, though, so the
same tier is weaker evidence — hence the **0.80** scale on its rating signal.

Because Depth takes the *maximum* rating evidence across judges and *sums* hard
volume, that scale-down can only ever be conservative: linking JungOl never
lowers a card. The same holds for Problem Solving (a sum) and for confidence
(an added term). Trust is 0.60 because the data comes from the `__data.json`
payload JungOl's own pages already serve — public, but a framework internal
rather than a documented API.

## Unsupported platforms

**Programmers** and **CodeTree** are not collected, and that is a deliberate
decision rather than a to-do. Neither exposes a public profile or API that works
without logging in: Programmers removed its public profile pages entirely and its
`robots.txt` disallows them, CodeTree's `robots.txt` disallows everything and its
API requires a JWT, and SWEA redirects every stats page to a login. Programmers'
terms of service also prohibit crawling and scraping.

The workaround the community uses — putting your account ID and password into a
repository secret — is not something codemaru will ask for or support. **codemaru
never handles platform credentials, cookies, or sessions**; it reads only what is
public.

## Caveats

- A transient fetch failure on one platform degrades that platform to `unavailable` (e.g. solved.ac temporarily blocked), which lowers the affected axes for that request. In production a last-successful **stale fallback** serves the previous good result so the tier doesn't flicker.
- `Depth`'s representative-project signal is **owner-only**: an org-owned flagship (e.g. `python/cpython`) is not attributed to a contributor — a limitation of public GitHub data.

---

[English](#how-a-codemaru-tier-is-computed) · [한국어](#codemaru-티어-산정-방식)

# codemaru 티어 산정 방식

실제 프로필(`bnbong`)을 예시로 점수 산정 파이프라인을 처음부터 따라갑니다. 

수치는 특정 시점 스냅샷(`scoreVersion` 0.4.0)이며 실시간 데이터에 따라 바뀝니다.

> 점수는 **공개 활동**을 요약한 것이지 절대적인 실력 평가가 아닙니다.

## 파이프라인

```
원시 플랫폼 데이터  →  5개 축 점수  →  overall  ─┐
                                               ├─→  tier = min(점수 기반 티어, confidence 상한)
데이터 충실도        →  confidence    →  상한  ──┘
```

1. 각 **축**은 몇 개의 **신호**(원시 카운트)를 가중평균한 값입니다.
2. 다섯 축을 하나의 **overall**(0–100)로 결합합니다.
3. **Confidence**(0–1)는 *검증 가능한* 데이터가 얼마나 있는지를 나타냅니다. 카드에는
   표시되지 않지만 도달 가능한 **최고 티어를 제한(cap)** 합니다.
4. 최종 **티어**는 점수 기반 티어와 confidence 상한 중 **낮은 쪽**입니다.

예시에 앞서, `386 → 78.4` 같은 "마법 화살표"를 두 가지 기본 개념으로 설명합니다.

## 기본 개념 1 — 원시 숫자를 0–100 점수로 변환

원시 카운트(커밋 386, stars 72 …)는 그대로 쓸 수 없습니다. 상한이 없기 때문에 각 원시값을 **체감 효용 감소(diminishing returns)** 곡선으로 0–100에 압축하며, 두 함수 중 하나를 씁니다.

**`logScore`** (상한 없는 카운트 — 커밋, stars, 푼 문제 수):

$$\mathrm{logScore}(v,s) = \min\left(100, \frac{\ln(1+v)}{\ln(1+s)}\times 100\right)$$

- $v$ = 원시값, $s$ = **포화(saturation)** 기준(점수가 ~100에 도달하는 값). $s$가 클수록 점수가 더 천천히 오릅니다.
- 예시 — 커밋, 포화 $s = 2000$:

$$\mathrm{logScore}(386,2000)=\frac{\ln(387)}{\ln(2001)}\times 100=\frac{5.96}{7.60}\times 100\approx \mathbf{78.4}$$

  이것이 `386 → 78.4` 단계입니다: 커밋 386개를 포화 2000으로 정규화하면 **100점 만점에 78.4점**입니다.

**`linScore`** (이미 자연스러운 최댓값이 있는 값 — 예: 365일 중 활동일):

$$\mathrm{linScore}(v,m) = \min\left(100, \frac{v}{m}\times 100\right)$$

  예: 활동일 127일 / 최대 $m = 365$ → $\frac{127}{365}\times100 \approx 34.8$.

## 기본 개념 2 — 신호들을 묶어 하나의 축으로

각 축은 여러 정규화된 신호를 **가중치**로 평균합니다. 신호 $s_i$, 가중치 $w_i$일 때:

$$\text{축} = \frac{\sum_i s_i \times w_i}{\sum_i w_i}$$

> **표기:** `×`는 항상 **곱셈**을 뜻합니다. 아래 표에서 각 신호는 한 행이며,
> **기여(contribution)** 열은 단순히 `점수 × 가중치`입니다. 축 점수는 기여들의 합입니다
> (여기서 가중치 합이 1이라 따로 나눌 필요가 없습니다).

다섯 축과 overall에서의 가중치:

| 축 | 신호 (출처) | overall 가중 |
| --- | --- | --- |
| Open Source | 커밋, 기여 repo, PR, 리뷰, 이슈 — 최근 1년 (GitHub) | 0.30 |
| Problem Solving | 저지 전체를 합산한 총 푼 문제 수 (solved.ac + LeetCode + JungOl) | 0.20 |
| Depth | 알고리즘 깊이(저지) **또는** 대표 소유 프로젝트, + 언어 다양성 | 0.20 |
| Consistency | 활동한 날, 최장 연속 기록 (GitHub) | 0.15 |
| Impact | stars, forks, followers, 공개 repo (GitHub) | 0.15 |

## 예시 — `bnbong`

입력: GitHub `bnbong`, solved.ac `bnbong`, LeetCode `bnbong`.

### Open Source (축 가중 0.30)

| 신호 | 원시값 | 정규화 (`logScore`, 포화) | 가중 | 기여 (점수 × 가중) |
| --- | --- | --- | --- | --- |
| 커밋 | 386 | 78.4 ($s=2000$) | 0.40 | 31.4 |
| 기여 repo | 13 | 64.2 ($s=60$) | 0.20 | 12.8 |
| PR | 44 | 71.8 ($s=200$) | 0.15 | 10.8 |
| 리뷰 | 0 | 0.0 ($s=150$) | 0.15 | 0.0 |
| 이슈 | 29 | 67.8 ($s=150$) | 0.10 | 6.8 |

$$\text{OpenSource}=31.4+12.8+10.8+0.0+6.8=\mathbf{61.8}$$

### Impact (축 가중 0.15)

| 신호 | 원시값 | 정규화 (`logScore`, 포화) | 가중 | 기여 |
| --- | --- | --- | --- | --- |
| stars | 72 | 53.6 ($s=3000$) | 0.45 | 24.1 |
| forks | 9 | 34.4 ($s=800$) | 0.20 | 6.9 |
| followers | 64 | 57.1 ($s=1500$) | 0.20 | 11.4 |
| 공개 repo | 43 | 86.1 ($s=80$) | 0.15 | 12.9 |

$$\text{Impact}=24.1+6.9+11.4+12.9=\mathbf{55.3}$$

### Consistency (축 가중 0.15)

`linScore`를 사용합니다(자연스러운 최댓값이 있는 값):

| 신호 | 원시값 | 정규화 (`linScore`, 최대) | 가중 | 기여 |
| --- | --- | --- | --- | --- |
| 활동일 | 127 | 34.8 ($m=365$) | 0.60 | 20.9 |
| 최장 연속 | 6 | 5.0 ($m=120$) | 0.40 | 2.0 |

$$\text{Consistency}=20.9+2.0=\mathbf{22.9}$$

### Problem Solving (축 가중 0.20)

풀이 수는 **저지 전체를 먼저 합산**한 뒤 한 번만 정규화합니다. 그래서 저지를 추가해도 점수가 오르기만 하고 희석되지 않습니다:

$$\text{ProblemSolving}=\mathrm{logScore}(\underbrace{229}_{\text{백준}}+\underbrace{2}_{\text{LeetCode}},2500)=\mathrm{logScore}(231,2500)\approx\mathbf{69.6}$$

### Depth (축 가중 0.20)

Depth는 **두 기둥 중 강한 쪽** + 작은 다양성 보너스입니다. 각 기둥도 가중평균입니다.

**기둥 A — 알고리즘 깊이** ($P_{\text{algo}}$):

| 신호 | 원시값 | 정규화 | 가중 | 기여 |
| --- | --- | --- | --- | --- |
| 백준 티어 | 12 | 40.0 (`linScore`, $m=30$) | 0.50 | 20.0 |
| 난이도 가중 풀이 | 3.0 | 23.1 (`logScore`, $s=400$) | 0.50 | 11.6 |

$$P_{\text{algo}}=20.0+11.6=\mathbf{31.6}$$

(*난이도 가중 풀이*는 어려운 문제에 더 큰 가중: gold ×0.3, platinum ×1, diamond ×2, ruby ×3. bnbong은 gold 10개 → $10\times0.3=3.0$.)

**기둥 B — 대표 프로젝트** ($P_{\text{project}}$, 가장 stars가 많은 *소유* repo 1개):

| 신호 | 원시값 | 정규화 (`logScore`, 포화) | 가중 | 기여 |
| --- | --- | --- | --- | --- |
| 대표 repo stars | 50 | 39.7 ($s=20000$) | 0.75 | 29.8 |
| 대표 repo forks | 4 | 18.9 ($s=5000$) | 0.25 | 4.7 |

$$P_{\text{project}}=29.8+4.7=\mathbf{34.5}$$

**다양성 보너스** — 언어 개수 정규화: $\mathrm{logScore}(12,12)=100$.

두 기둥은 **max**로 결합되고(어느 한쪽만으로도 100 도달 가능), 다양성은 *남은 여유분*만(최대 +15%) 채웁니다. 그래서 약한 신호가 강한 신호를 끌어내리지 못합니다:

$$\text{primary}=\max(P_{\text{algo}},P_{\text{project}})=\max(31.6,34.5)=34.5$$

$$\text{Depth}=\text{primary}+(100-\text{primary})\times 0.15\times\frac{\text{breadth}}{100}=34.5+(100-34.5)\times 0.15\times 1.0\approx\mathbf{44.3}$$

### Overall

다섯 축을 가중치로 결합합니다:

$$\text{overall}=0.30O+0.20P+0.20D+0.15C+0.15I$$

$$=0.30(61.8)+0.20(69.6)+0.20(44.3)+0.15(22.9)+0.15(55.3)=\mathbf{53.0}$$

### Confidence와 티어 상한

Confidence는 "*신뢰할 만한 데이터가 실제로 얼마나 있나?*"를 묻습니다. 각 플랫폼은 존재 여부가 아니라 **데이터 볼륨**에 비례한 factor를 더하므로, 갓 만든 계정은 거의 기여하지 않습니다.

저지의 factor는 "무료(free)" 임계 10문제를 둡니다 — 처음 몇 문제는 0으로 쳐서, 빈 계정이 티어를 부풀리지 못하게 합니다:

$$f_{\text{judge}}=\text{trust}\times\frac{\mathrm{logScore}\big(\max(0, \text{solved}-10), s\big)}{100}$$

- GitHub factor — 최근 활동 *또는* 대표 소유 프로젝트 중 **강한 쪽** (bnbong은 최근 활동이 우세): $f_{\text{gh}} = 0.979$
- solved.ac factor: trust $1.0$, $\mathrm{logScore}(229-10,2200)/100 \Rightarrow f_{\text{solvedac}} = 0.701$
- LeetCode factor: 2문제뿐이라 $\max(0,2-10)=0$ → $f_{\text{leetcode}} = 0$
- JungOl factor: 핸들을 넣지 않았으므로 항 자체가 없습니다

$$\text{confidence}=0.6f_{\text{gh}}+0.25f_{\text{solvedac}}+0.15f_{\text{leetcode}}+0.10f_{\text{jungol}}=0.6(0.979)+0.25(0.701)+0+0=\mathbf{0.763}$$

저지 가중치는 나눠 갖지 않고 **더합니다**. 나중에 저지가 추가돼도 기존 사용자의
confidence가 내려가지 않으며, 가중치 합이 1을 넘는 부분은 기존 $[0,1]$ clamp가
처리합니다.

confidence **0.763**은 상한을 **Master**까지 엽니다.

### 최종 티어

$$\text{tier}=\min(\underbrace{\text{Gold}}_{\text{점수 }53.0\in[45,58)}, \underbrace{\text{Master}}_{\text{confidence 상한}})=\textbf{Gold}$$

overall 점수(53.0)가 Gold 구간에 들고, confidence 상한(Master)이 더 높아 티어를 끌어내리지 않습니다. **bnbong → Gold.**

## Confidence, 상한, Maru

- Confidence는 플랫폼 *개수*가 아니라 *검증 가능한 풀이량/활동*에 비례합니다 — 방금 만든 몇 문제짜리 계정을 연결해도 거의 0입니다.
- GitHub confidence는 **대표 소유 프로젝트**도 함께 반영합니다 — 역사적으로 의미 있는 대표작이 있으면 최근 활동이 잠잠해도 상한이 낮게 묶이지 않습니다.
- 한 분야가 강한 **단일 출처** 프로필(예: GitHub만)도 **Master**까지 도달할 수 있습니다.
- 최고 티어 **Maru**는 오픈소스와 알고리즘 양쪽 모두 깊은 **멀티플랫폼 오각형**에만 주어집니다.

## 저지별 반영 지점

모든 저지는 같은 두 축에 **더하는 방식으로만** 반영됩니다.

| 저지 | Problem Solving | Depth | trust | 포화점 | confidence 가중 |
| --- | --- | --- | --- | --- | --- |
| solved.ac / 백준 | 푼 문제 수 | 티어(`linScore`, $m=30$) + 난이도 가중 풀이 | 1.00 | 2200 | 0.25 |
| LeetCode | 푼 문제 수 | 1200 초과분 콘테스트 레이팅 + hard 풀이 | 0.75 | 1400 | 0.15 |
| 정올(JungOl) | 푼 문제 수 | 티어 × **0.80** + 난이도 가중 풀이 | 0.60 | 900 | 0.10 |

정올은 solved.ac와 같은 0~30 티어 스케일을 씁니다(정올 스스로 티어를 solved.ac AC
레이팅 기준으로 계산한다고 밝히고 있습니다). 그래서 난이도 밴드와 티어 이름을 그대로
가져다 씁니다. 다만 문제 풀 규모가 백준보다 훨씬 작아 같은 티어라도 근거가 약하기
때문에, 레이팅 신호에 **0.80** 보정을 곱합니다.

Depth는 저지들의 레이팅 근거 중 **최댓값**을 쓰고 난이도 가중 풀이는 **합산**하므로,
이 보정은 한쪽으로만 보수적으로 작용합니다. 즉 정올을 연결해서 점수가 내려가는 일은
없습니다. Problem Solving(합산)과 confidence(가산)도 마찬가지입니다. trust가 0.60인
이유는 데이터 출처가 정올 페이지가 이미 내려주는 `__data.json`이기 때문입니다. 공개된
값이지만 문서화된 API가 아니라 프레임워크 내부 포맷입니다.

## 지원하지 않는 플랫폼

**프로그래머스**와 **코드트리**는 수집하지 않습니다. 아직 안 한 것이 아니라 하지 않기로
정한 것입니다. 두 곳 모두 로그인 없이 볼 수 있는 공개 프로필이나 API가 없습니다.
프로그래머스는 공개 프로필 페이지 자체를 없앴고 `robots.txt`로도 막아 뒀으며,
코드트리는 `robots.txt`가 전체를 막고 API는 JWT를 요구합니다. SWEA는 모든 통계
페이지가 로그인으로 넘어갑니다. 프로그래머스 이용약관은 크롤링·스크래핑도 금지합니다.

커뮤니티에서 쓰는 우회 방법 — 계정 아이디와 비밀번호를 저장소 시크릿에 넣는 방식 —
은 codemaru가 요구하지도, 지원하지도 않습니다. **codemaru는 플랫폼 자격증명이나
쿠키, 세션을 다루지 않습니다.** 공개된 데이터만 읽습니다.

## 유의사항

- 한 플랫폼의 일시적 조회 실패는 해당 플랫폼을 `unavailable`로 떨어뜨려(예: solved.ac 일시 차단) 그 요청의 해당 축을 낮춥니다. 운영 환경에서는 마지막 성공값을 쓰는 **stale fallback**이 직전 정상 결과를 대신 서빙해 티어가 깜빡이지 않습니다.
- `Depth`의 대표 프로젝트 신호는 **소유(owner) repo 한정**입니다: org 소유 대표작 (예: `python/cpython`)은 공개 GitHub 데이터의 한계로 기여자에게 귀속되지 않습니다.
