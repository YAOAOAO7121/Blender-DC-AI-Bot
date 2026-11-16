# Issue 追蹤：GitHub

這個 repo 的 issue 和規格都記在 GitHub Issues（`YAOAOAO7121/Blender-DC-AI-Bot`），所有操作都用 `gh` CLI。

## 慣例

- **建立 issue**：`gh issue create --title "..." --body "..."`。多行內文用 heredoc。
- **讀取 issue**：`gh issue view <number> --json number,title,body,labels,comments`。
- **列出 issue**：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，視需要加上 `--label` 和 `--state` 篩選。
- **設為某個 issue 的子 issue**：`gh issue create --parent <parent> ...`，或事後用 `gh issue edit <parent> --add-sub-issue <child>`（`gh` 2.94 以上）。較舊的 `gh`：`gh api --method POST repos/<owner>/<repo>/issues/<parent>/sub_issues -F sub_issue_id=<child-db-id>`（database id，取法同下方 **Blocking**）。不能用子 issue 時，在子 issue 內文最上面寫 `Part of #<parent>`。
- **留言**：`gh issue comment <number> --body "..."`
- **加上／移除標籤**：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **關閉**：`gh issue close <number> --comment "..."`

repo 由 `git remote -v` 推斷；在 clone 裡執行 `gh` 會自動判斷。

## Pull request 是否當成需求來源

**PRs as a request surface: no.** _（如果這個 repo 把外部 PR 當成功能需求，改成 `yes`；`/triage` 會讀這個設定。）_

設成 `yes` 時，PR 和 issue 走同一套標籤與狀態，改用對應的 `gh pr` 指令：

- **讀取 PR**：`gh pr view <number> --comments`，看差異用 `gh pr diff <number>`。
- **列出待分類的外部 PR**：`gh api --paginate 'repos/{owner}/{repo}/pulls?state=open' --jq '.[] | select(.author_association | IN("OWNER","MEMBER","COLLABORATOR") | not) | {number, title, author: .user.login, author_association, labels: [.labels[].name]}'`。
- **留言／標籤／關閉**：`gh pr comment`、`gh pr edit --add-label`/`--remove-label`、`gh pr close`。

GitHub 的 issue 和 PR 共用同一組編號，單寫 `#42` 可能是兩者之一：先試 `gh pr view 42`，不是再用 `gh issue view 42`。

## 技能說「發布到 issue tracker」時

建立一個 GitHub issue。

## 技能說「取得相關的 ticket」時

照上面 **讀取 issue** 的方式讀。

## Wayfinding 操作

給 `/wayfinder` 用。**map** 是一個 issue，底下的 **child** issue 是各個 ticket。

- **Map**：一個標上 `wayfinder:map` 的 issue，內文放 Notes / Decisions-so-far / Fog。`gh issue create --label wayfinder:map`。
- **Child ticket**：以 GitHub 子 issue 連到 map 的 issue（見 **設為某個 issue 的子 issue**）。不能用子 issue 時，把 child 加進 map 內文的 task list，並在 child 內文最上面寫 `Part of #<map>`。標籤：`wayfinder:<type>`（`research`/`prototype`/`grilling`/`task`）。認領後指派給負責的開發者。
- **Blocking**：用 GitHub **原生的 issue dependencies**，這是標準、在介面上看得到的表示法。新增相依：`gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`，其中 `<blocker-db-id>` 是 blocker 的數字 **database id**（`gh api repos/<owner>/<repo>/issues/<n> --jq .id`，**不是** `#number` 或 `node_id`）。GitHub 會回報 `issue_dependencies_summary.blocked_by`（只算還沒關的 blocker，是即時的關卡）。不能用 dependencies 時，在 child 內文最上面寫 `Blocked by: #<n>, #<n>`。所有 blocker 都關閉後，ticket 才算解除封鎖。
- **Frontier 查詢**：列出 map 底下還開著的 child（`gh issue list --state open`，限定在 map 的子 issue／task list），去掉有未關閉 blocker（`issue_dependencies_summary.blocked_by > 0`，或 `Blocked by` 那行有還開著的 issue）或已有指派人的；依 map 裡的順序取第一個。
- **認領**：`gh issue edit <n> --add-assignee @me`，這是該次工作的第一個寫入動作。
- **完成**：`gh issue comment <n> --body "<答案>"`，接著 `gh issue close <n>`，再把脈絡指標（摘要＋連結）補到 map 的 Decisions-so-far。
