# 領域文件

engineering 技能在探索程式碼時，怎麼使用這個 repo 的領域文件。

## 探索前先讀

- 根目錄的 **`GLOSSARY.md`**，或
- 根目錄若有 **`GLOSSARY-MAP.md`**：它指向每個脈絡各自的 `GLOSSARY.md`，讀跟主題有關的那幾份。
- **`docs/adr/`**：讀跟這次要動的區域有關的 ADR。多脈絡的 repo 也要看 `src/<context>/docs/adr/` 裡的脈絡專屬決策。

這些檔案不存在時，**直接繼續、不用提**。不要指出它們不存在，也不要一開始就建議建立。`/domain-modeling` 技能（透過 `/grill-with-docs` 和 `/improve-codebase-architecture` 進入）會在名詞或決策真正定案時才建立它們。

這個 repo 是單一脈絡（single-context）。

## 檔案結構

單一脈絡的 repo（大多數 repo，包括這個）：

```
/
├── GLOSSARY.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

多脈絡的 repo（根目錄有 `GLOSSARY-MAP.md`）：

```
/
├── GLOSSARY-MAP.md
├── docs/adr/                          ← 整個系統的決策
└── src/
    ├── ordering/
    │   ├── GLOSSARY.md
    │   └── docs/adr/                  ← 該脈絡的決策
    └── billing/
        ├── GLOSSARY.md
        └── docs/adr/
```

## 用詞彙表的用語

輸出裡提到領域概念時（issue 標題、重構提案、假設、測試名稱），用 `GLOSSARY.md` 定義的用語。不要換成詞彙表明確避免的同義詞。

需要的概念還不在詞彙表裡，就是個訊號：要嘛你在發明專案沒在用的說法（重新考慮），要嘛真的有缺口（記下來給 `/domain-modeling`）。

## 標出與 ADR 的衝突

輸出跟現有 ADR 矛盾時，要明確指出，不要默默推翻：

> _與 ADR-0007（event-sourced orders）矛盾，但值得重新討論，因為……_
