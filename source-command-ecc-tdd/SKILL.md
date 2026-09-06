---
name: "source-command-ecc-tdd"
description: "ECC TDD 스킬로 승인된 계획을 실패 테스트부터 구현"
---

# source-command-ecc-tdd

Use this skill when the user asks to run the migrated source command `ecc-tdd`.

## Command Template

현재 설치된 ECC의 TDD 관련 스킬을 사용해서 승인한 계획을 구현해줘.

반드시 다음 순서로 진행해줘.
1. 실패하는 테스트를 먼저 작성한다.
2. 테스트가 예상한 이유로 실패하는지 확인한다.
3. 테스트를 통과하는 최소한의 코드를 작성한다.
4. 전체 테스트를 실행한다.
5. 중복과 복잡도를 정리한다.
6. 테스트를 다시 실행한다.

각 단계가 끝날 때 실행한 테스트와 결과를 보여줘.
테스트 증거 없이 완료됐다고 말하지 마.
