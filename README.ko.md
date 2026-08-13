<p align="center">
  <img src="assets/oh-my-hermes-wordmark.png" alt="OH-MY-HERMES" width="100%" style="display:block;max-width:none;height:auto">
</p>

<table align="center">
  <tr>
    <td width="50%" align="center">
      <img src="assets/hermes-desktop.gif" alt="Hermes Desktop running an OMH workflow" width="380" height="266"><br>
      <sub><b>Hermes 데스크톱, oh-my-hermes와 함께.</b><br>워크플로를 고르면, 만들기 전에 먼저 확인합니다.</sub>
    </td>
    <td width="50%" align="center">
      <img src="assets/hermes-cli.gif" alt="Hermes CLI running an OMH workflow" width="380" height="266"><br>
      <sub><b>Hermes CLI, oh-my-hermes와 함께.</b><br>쓰던 터미널에서 같은 워크플로를.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="assets/hermes-messenger.gif" alt="Hermes messenger app running an OMH workflow" width="380" height="266"><br>
      <sub><b>Hermes 메신저 앱, oh-my-hermes와 함께.</b><br>스레드에서 요청하면 같은 스레드로 답합니다.</sub>
    </td>
    <td width="50%" align="center">
      <img src="assets/omh-setup.gif" alt="omh setup installing the OMH workflows" width="380" height="266"><br>
      <sub><b><code>omh setup</code>, 명령 하나로.</b><br>워크플로를 설치하고 Hermes에 연결합니다.</sub>
    </td>
  </tr>
</table>

# oh-my-hermes

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.ko.md">한국어</a> |
  <a href="README.ja.md">日本語</a> |
  <a href="README.zh.md">中文</a>
</p>

<p align="center">
  <a href="https://github.com/rlaope/oh-my-hermes"><img alt="GitHub" src="https://img.shields.io/badge/github-rlaope%2Foh--my--hermes-181717?logo=github"></a>
  <a href="https://github.com/NousResearch/hermes-agent"><img alt="Hermes Agent" src="https://img.shields.io/badge/Hermes%20Agent-NousResearch-6f42c1?logo=github"></a>
  <a href="https://github.com/rlaope/oh-my-hermes"><img alt="OMH stars" src="https://img.shields.io/github/stars/rlaope/oh-my-hermes?style=flat&logo=github"></a>
  <a href="https://github.com/NousResearch/hermes-agent"><img alt="Hermes Agent stars" src="https://img.shields.io/github/stars/NousResearch/hermes-agent?style=flat&logo=github"></a>
</p>

<p align="center">
  <img src="assets/hermes-agent-hero.png" alt="Oh My Hermes" width="720">
</p>

<p align="center">
  <strong>한 번 설치하세요. Hermes는 그대로 두고, 더 강한 운영층을 더하세요.</strong>
  <em>계획, 조사, 제작, 코딩 handoff, 운영, 프로젝트 기억을 명확한 증거 경계와 함께 제공합니다.</em>
</p>

<p align="center">
  <img src="assets/oh-my-hermes-agent-poster.png" alt="Oh My Hermes Agent poster" width="720">
</p>

**oh-my-hermes**(OMH)는
[Hermes Agent](https://github.com/NousResearch/hermes-agent)의 평범한 요청을
알맞은 기능, 유용한 다음 단계, 그리고 실제로 일어난 일과 아직 일어나지 않은
일에 대한 정직한 상태로 바꿉니다. Hermes를 대체하거나 코딩 executor를 숨기지
않고, 이미 사용 중인 Hermes 작업 흐름을 강화합니다.

[Website](https://rlaope.github.io/oh-my-hermes/) ·
[Documentation](docs/README.md) ·
[Installation](docs/INSTALLATION.md) ·
[Capabilities](docs/CAPABILITIES.md) ·
[Capability Impact](docs/CAPABILITY_IMPACT.md) ·
[Agent Install](INSTALL_FOR_AGENTS.md) ·
[GitHub Pages site](site/index.html)

> [!NOTE]
> OMH는 Hermes를 자연어 표면으로 유지하고 명확한 증거 경계를 갖춘 전문 운영층을
> 추가합니다.
>
> <p align="center">
>   <img src="assets/omh-terminal-boot-banner.png" alt="OH-MY-HERMES terminal banner listing available tools, grouped skills, OMH specialists, infrastructure, and the model pool on Hermes Agent" width="1080">
> </p>
>
> <p align="center">
>   <img src="assets/hermes-omh-terminal-orchestration.png" alt="Hermes Agent and OH-MY-HERMES working side by side" width="1080">
> </p>
>
> <p align="center">
>   <img src="assets/friren-agent-omh-callout.png" alt="Friren Agent explaining OMH in Art&Engine" width="720">
> </p>
## 빠른 시작

**로컬 명령과 관리형 skill을 설치합니다:**

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
```

**Windows(PowerShell 5.1+)에서는:**

```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
omh setup
```

**Hermes skill tap 경로:**

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/omh-routing --yes
```

**또는 Your AI Agent에게 요청합니다:**

```text
Hey Agent, Install this >> https://github.com/rlaope/oh-my-hermes <<
```

**업데이트와 상태 점검:**

```sh
omh update
omh doctor
```

`--full` 설치를 core로 되돌리는 것 같은 유지보수 경로는
[Installation](docs/INSTALLATION.md#reconciling-an-existing-full-install-back-to-core)에
있습니다.

## 권장 모델

OMH에는 다음과 같이 편집 가능한 카테고리별 권장 모델이 포함되어 있습니다.

| 카테고리 | 권장 모델 |
| --- | --- |
| `ultrabrain` | GPT-5.6 Sol |
| `deep` | GPT-5.6 Terra |
| `unspecified-high` | Kimi K3, 다음 Claude Opus 5 |
| `unspecified-low` | GLM 5.2, 다음 GLM 5.2 Ultrafast |
| `visual-engineering` | Claude Fable 5, 다음 Kimi K3 |

Hermes에게 **모델을 설정해 줘**라고 요청해 검토하거나 변경할 수 있습니다.
이는 편집 가능한 선호이며 benchmark 결과가 아닙니다. 자세한 설정, fallback,
provider, 소유권 규칙은
[Guided Model Setup](docs/INSTALLATION.md#guided-model-setup)을 참조하세요.

## 울트라 스킬

<p align="center">
  <img src="assets/omh-character-badge.png" alt="Oh My Hermes character mark" width="170">
</p>

12개의 `ulw-` workflow. 대화에서 트리거만 말하면 Hermes가 라우팅합니다 —
전체 카탈로그는 [Workflow Reference](docs/WORKFLOWS.md).

| Skill | 무엇을 하나 |
| --- | --- |
| ⚡ `ulw-context` | 검토된 프로젝트 용어를 맞추고, 확인된 후보를 캡처하며, 용어에 라우팅 권한을 주지 않은 채 다음 결정 지점을 질문합니다. |
| ⚡ `ulw-interview` | 원하는 게 정확히 뭔지 알 때까지 한 번에 하나씩 묻습니다. |
| ⚡ `ulw-research` | 실제 코드와 웹을 뒤져 조사하고, 출처를 남기고, 의심스러우면 검증합니다. |
| ⚡ `ulw-plan` | 선택지 비교, 리스크, 완료 기준까지 합의된 검토 계획을 만듭니다. |
| ⚡ `ulw-work` | 승인된 계획을 같은 파일을 건드리지 않는 병렬 레인으로 실행합니다. |
| ⚡ `ulw-ralph` | 한 명이 끝까지 책임집니다 — 구현, 검증, 리뷰를 될 때까지 반복. |
| ⚡ `ulw-team` | 여러 작업자, 하나의 작업 목록, 충돌 없음. |
| ⚡ `ulw-loop` | 계획 → 구현 → 리뷰를 목표가 진짜 통과할 때까지 돌립니다. |
| ⚡ `ulw-goal` | 체크포인트가 있는 장기 목표 — 컨텍스트가 날아가도 멈춘 곳부터 다시. |
| ⚡ `ulw-process` | 작업 하나를 리서치부터 PR까지 끝까지 끌고 갑니다. |
| ⚡ `ulw-qa` | 일부러 험한 시나리오로 공격해 보고, 깨지는 곳을 고칩니다. |
| ⚡ `ulw-perf` | 어디가 진짜 느리고 비싼지 측정한 뒤, 핫패스를 하나씩 고칩니다. |
## OMH가 더하는 것

OMH는 **105개**의 설치형 workflow skill을 사람이 이해하기 쉬운 6개 기능군으로
제공합니다.

그중 12개는 workflow engine입니다 - `context`, `deep-interview`, `loop`, `ralph`, `ralplan`, `research`, `team`, `ultragoal`, `ultraperf`, `ultraprocess`, `ultraqa`, `ultrawork` - 이들은 `ulw-` 라벨로 렌더링되어
상태 줄만 봐도 어떤 종류의 skill이 도는지 알 수 있습니다. 나머지 93개는 `omh-`를
붙입니다. canonical name은 어느 쪽도 바뀌지 않습니다.

| 기능군 | Hermes가 더 잘할 수 있는 일 |
| --- | --- |
| **계획과 결정** | 모호한 목표를 명확히 하고, 검토된 계획과 durable goal loop를 준비합니다. |
| **학습과 수집** | 출처 탐색, 논문 설명, 데이터 점검, 근거 기반 브리프를 준비합니다. |
| **자료와 시각물 제작** | 웹, 이미지, 문서, 발표 자료, PDF, 포스터를 형식별 품질 게이트와 함께 만듭니다. |
| **코딩 위임과 배포** | Codex, Claude Code, Hermes runtime 또는 선택한 executor에 전달할 명확한 handoff를 준비합니다. |
| **운영과 관찰** | 설정, 서비스 품질, 릴리스, 장애, 자동화, 세션, workflow learning을 점검합니다. |
| **지식 보존** | 검토된 프로젝트 기억을 만들고 외부 지식 시스템을 provider-neutral 경계로 연결합니다. |

전체 목록과 trigger, harness, 증거 규칙은
[Workflow Reference](docs/WORKFLOWS.md)에 있습니다.

**하이라이트**

| 기능 | 사용 방법 | 동작 |
| --- | --- | --- |
| 🧭 **명확화와 계획** | `omh-plan` · `omh-decide` · `omh-meeting-brief` | 모호한 요청을 명확한 목표, 제약, trade-off, 완료 기준, 그리고 그대로 전달할 수 있는 계획으로 바꿉니다. |
| ⚡ **레버리지를 활용한 실행** | `omh-idea-to-deploy` · `omh-cto-loop` · `omh-running-work-board` | 빠른 병렬 작업부터 지속적인 다단계 실행까지 확장하면서도 소유권, 체크포인트, 검증을 계속 볼 수 있게 유지합니다. |
| 🔬 **조사와 학습** | `omh-best-practice-research` · `omh-research-brief` · `omh-paper-learning` | 최신성, 출처 품질, 아직 해소되지 않은 불확실성 경계를 함께 표시하며 근거 기반 증거를 찾고 종합합니다. |
| 🛠️ **안전한 코딩과 배포** | `omh-code-review` · `omh-build-failure-triage` · `omh-verification-gate` | executor에 종속되지 않는 코딩 작업을 준비하고, review·QA·CI·merge에 대한 주장은 관측된 증거에만 근거하게 만듭니다. |
| 🎨 **완성도 높은 산출물 제작** | `omh-design-quality-gate` · `omh-materials-package` · `omh-deliverable-package` · `omh-image-cards` | 콘텐츠, 완성도, 접근성, 렌더링 품질 게이트를 기준으로 웹사이트, 시각 자료, 보고서, 발표 자료, 문서, PDF, 포스터, 패키지를 만듭니다. |
| 🧠 **기억과 운영** | `omh-memory-new` · `omh-memory-sync` · `omh-ops-observability-card` · `omh-doctor` | 프로젝트 기억을 검토 우선으로 유지하고, 운영 준비 상태를 보여주며, provider나 시스템 상태를 지어내지 않고 다음 복구 행동을 제시합니다. |
| 🔌 **경계를 숨기지 않는 연결** | `omh-toolbelt-readiness` · `omh-external-connector-readiness` · `omh-agent-board` | 작업이 의존하기 전에 필요한 도구·connector·agent 표면이 실제로 준비됐는지 확인하고, host 로드·도구 사용·외부 provider 접근을 각각 별도로 관측할 수 있게 유지합니다. |
## 실제 업무를 위한 설계

<p align="center">
  <img src="assets/built-for-real-work-orchestration.png" alt="OMH orchestrating coding agents and creative tools" width="900">
</p>

> **OMH (Oh-My-Hermes)** — 누구나 hermes-agent를 전문가처럼 쓸 수 있게 합니다.<br>
> AI 에이전트를 위한 강력한 지능 하네스입니다.

**🧭 명령어 목록이 아닌, 더 똑똑한 라우터.** 영어, 한국어, 일본어, 중국어,
스페인어, 프랑스어, 독일어, 힌디어 요청을 번역 API 없이 로컬에서 분류합니다.
OMH는 추천 기능군, skill, 담당자, 다음 행동, 그리고 아직 증거가 아닌 부분을
함께 돌려줍니다.

**🤝 더 나은 코딩 handoff.** 저장소 제약, 합의된 범위, worktree 및
session-isolation 지침, 로컬에서 사용 가능한 skill, 완료 기준, review
기대치, verification gate를 담을 수 있습니다. Codex, Claude Code, Hermes,
generic executor는 모두 숨은 기본값이 아니라 명시적인 담당자로 남습니다.

**🎨 품질을 아는 제작.** Frontend, 접근성, 이미지, 보고서, 발표 자료, 문서,
스프레드시트, PDF, 포스터, 공유 패키지 요청은 전용 제작·QA 지침을 거칩니다.
준비된 브리프를 생성되었거나 시각적으로 검증된 산출물처럼 보여주지 않습니다.

**🔍 주장보다 증거.** OMH는 준비된 의도, 관측된 runtime 이벤트, 검증된
결과를 구분합니다. handoff는 executor가 실행했다거나 review가 통과했다거나
CI가 성공했다거나 배포가 끝났다거나 PR이 merge됐다는 주장 없이도 준비될 수
있습니다.

**🧠 검토 우선 프로젝트 기억.** OMH는 프로젝트 기억 후보를 승인된 기록과
분리해서 관리하고, 검토를 거쳐 준비된 맥락만 이후 handoff에 다시 불러옵니다.
불투명한 Hermes 내부 기억을 읽거나 바꿨다고 주장하지 않습니다.

**🔌 provider-neutral 운영.** metric, wiki, browser, image, video, connector
시스템은 명시적인 외부 provider 계약 뒤에 있습니다. 실제로 연결하거나
호출하지 않은 provider를 사용했다고 주장하지 않으면서 제공된 데이터를
검증하고 분석할 수 있습니다.

**🏛️ Hermes-native, executor-neutral 아키텍처.** Hermes는 여전히 채팅,
명확화, 계획, 조사, 상태 표면을 담당합니다. 선택된 executor가 구현을 맡고,
OMH는 그 작업을 둘러싼 로컬 계약, 라우팅, 기억, 품질 게이트, 증거 경계를
제공합니다.

**🧱 local-first 제어면.** OMH의 핵심 라우팅, catalog, manifest, 주장
규칙은 결정적인 로컬 표면입니다. 외부 호출과 provider 접근은 코어 내부에
숨겨진 동작이 아니라 명시적인 통합으로 남습니다.
## 주장보다 증거

OMH는 직접 본 것만 일어났다고 말합니다. 화면에 뜨는 상태는 항상 두 부분입니다:
어느 단계인지, 그리고 OMH가 그걸 얼마나 확신하는지.

| 표시 | 의미 |
| --- | --- |
| `Plan · not run` | prompt나 plan이 준비됐습니다. **아직 아무것도 안 돌았습니다.** |
| `Code · running` | executor가 지금 돌고 있고 OMH가 보고 있습니다. |
| `Code · reported done` | executor가 끝났다고 말했습니다. 결과는 아무도 확인 안 했습니다. |
| `Test · verified` | test, review, CI gate가 실제로 통과했습니다. |

중요한 건 아래에서 두 번째 줄입니다. executor가 끝났다고 말한 것과 결과가
확인된 것은 다른데, 대부분의 도구가 둘 다 "완료"라고 씁니다.
## 문서

- [문서 지도](docs/README.md)
- [설치와 업데이트](docs/INSTALLATION.md)
- [제품 방향과 경계](docs/DIRECTION.md)
- [아키텍처](docs/ARCHITECTURE.md)
- [기능 manifest](docs/CAPABILITIES.md)
- [Workflow reference](docs/WORKFLOWS.md)
- [역할](docs/ROLES.md)
- [활용 사례](docs/APPLICATION_CASES.md)
- [릴리스와 개발](docs/RELEASE.md)
## 개발

```sh
PYTHONPATH=tests uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
uv run python -m omh.cli docs workflows --check
git diff --check
```

OMH는 [Team Art & Engineering](https://rlaope.github.io/artengine-lab/)의
공개 프로젝트로 개발되고 있습니다. 프로젝트 소식은
[@rlaope](https://github.com/rlaope)에서 확인할 수 있습니다.
