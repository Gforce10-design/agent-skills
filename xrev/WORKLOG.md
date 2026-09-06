# WORKLOG — xrev 스킬 생성

## 2026-04-02 세션

### 작업 내용
1. **xrev 스킬 설계 및 구현** (`~/.claude/skills/xrev/SKILL.md`)
   - 3단계 교차 검증 파이프라인: codex:rescue → code-review → codex:adversarial-review
   - 스코프: staged/unstaged/untracked 우선 → 직전 커밋 fallback
   - 재실행 루프: 최대 10회 + 동일 결과 반복 시 즉시 중단

2. **벤치마크 테스트**
   - 의도적 결함 코드로 with-skill vs without-skill 비교
   - xrev: 18.3건 발견 (67% 향상), 시간 1.87x

3. **xrev on xrev (자기 교차 검증)**
   - codex:rescue 4회 + code-review 4회 + adversarial-review 2회 = 총 10회 리뷰
   - 4회 재실행 후 Critical/Major 0건 수렴 → WARN 완료

4. **G3 배포**
   - `scp`로 `192.168.10.2:C:/Users/sudol/.claude/skills/xrev/SKILL.md` 복사 완료

### 핵심 결정 & rationale
| 결정 | 이유 |
|---|---|
| Phase 3에 codex:adversarial-review 사용 (codex:rescue 아님) | 전용 적대적 리뷰 모드가 별도로 존재 |
| 수정 시 Phase 1부터 전체 재실행 | 후속 수정이 이전 Phase의 회귀 버그를 만들 수 있음 |
| 오케스트레이터 Claude가 Phase 3 수정안 직접 작성 | 모델 이름 하드코딩 회피, 서브에이전트 위임 시 품질 저하 우려 |
| Write guard에 git stash 대신 git diff --stat 비교 | stash가 작업 트리를 변경하여 리뷰 대상을 오염시키는 부작용 |
| 이슈 기록 MVP: 대화 컨텍스트 내 유지 | 별도 파일/DB 불필요, 한 세션 내 루프 감지 용도로 충분 |
| Minor 스킵은 기록에서 제외 | 재실행 시 동일 결과로 오판하여 구조적 문제로 잘못 중단하는 것 방지 |

### 수렴된 반복 이슈 (실전에서 관찰 필요)
- fingerprint 정밀도 (자연어 비교의 한계)
- shell 호환성 (bash 예시가 PowerShell에서 직접 실행 불가)
- severity 라벨 의존 (외부 스킬 출력 형식 비표준)

### 피드백 메모리
- `feedback_verify_existing_skills.md` — 새 스킬 설계 시 플러그인 명령어 전수 확인 필수
- `feedback_defend_reasoning.md` — 반론에 쉽게 입장 바꾸지 말고 논리적 근거로 설득
- `feedback_memory_folder_expansion.md` — 메모리 폴더 확장 시점 감지 및 제안

## 2026-04-03 세션

### 작업 내용
1. **메모리 구조 개선**
   - 평면 구조 → 타입별 폴더(user/, feedback/, project/) + 개별 파일 유지
   - Codex 검증: 타입별 통합(단일 파일)은 비추, 폴더 분류가 최적
   - MEMORY.md 인덱스를 섹션별로 재구성

2. **WORKLOG 위치 결정**
   - cowork 세션 폴더 + skills 디렉토리 양쪽에 유지
   - cowork: 세션 아카이브 / skills: 개발 참조용

### 핵심 결정 & rationale
| 결정 | 이유 |
|---|---|
| 타입별 폴더 + 개별 파일 (통합 아님) | Codex 검증: 통합 시 검색 정밀도·수정 국소성 손실 |
| WORKLOG를 skills 디렉토리에도 배치 | 새 세션에서 스킬 수정 시 cowork 폴더를 자동 탐색하지 않음 |
| 폴더 확장 시점을 Claude가 감지 | 사용자가 메모리 구조를 직접 관리하기 어려움 |

