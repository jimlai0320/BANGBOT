BANG! 骰子版 Telegram BOT　v0.8.1｜老酒館正式素材整合準備版
==========================================================

【請先閱讀】本版不是「老酒館所有模組已可玩的完成版」。
本包以原版 v0.7.9 的功能及 v0.8.0 擴充基礎版為基準。
已完整收錄、分類並測試老酒館目前確認的正式圖片。
程式依然阻擋「尚未開發完成」的老酒館模組開局，避免錯誤套用原版規則。

現在能用什麼：
- 原版 3～8 人 Telegram BOT（原有規則、AI、私訊身分、牌桌、動畫維持原狀）。
- 大廳已有老酒館五模組的設定選單（僅預覽；不能開始未實作的模組）。
- 8 張角色卡／8 張人物頭像／9 張特殊身分卡。
- 大嘴巴 6 面、膽小鬼 6 面，已由六面原圖分割成 12 個獨立 PNG（各 900px）。
- 新版酋長箭 1 張（採最後定稿的華麗版本）、7 枚鬼魂標記。
- 鬼魂卡、鬼魂叛徒卡、鬼魂圖示、鬼魂回合橫式標牌。
- saloon_assets.py 提供安全的素材查詢 API；SALOON_ASSETS_MANIFEST.json 為唯一圖檔/角色對應。

正式檔案：
  assets/old_saloon/cards/*.png          8 角色卡
  assets/old_saloon/avatars/*.png        8 頭像
  assets/old_saloon/roles/*.png          9 特殊身分卡
  assets/old_saloon/dice/{loudmouth,coward}/*.png 各 6 個骰面
  assets/old_saloon/dice/sheets/         2 張來源六宮格（供視覺核對）
  assets/old_saloon/arrows/chief_arrow.png
  assets/old_saloon/ghost/tokens/*.png   7 鬼魂標記
  assets/old_saloon/ghost/               鬼魂卡、鬼魂回合及人物圖示
  assets/old_saloon/previews/            可直接確認縮圖畫風的總覽

美術注意：
- 人物頭像是先前已確認的獨立生成圖；正式套上桌前須人工檢查是否與卡面同一張臉。
- 卡上文字雖已確認美觀，正式套入程式之前仍要按官方英文規則核對技能全文及生命值。
- 本包新增素材獨立存在，不覆蓋任何 assets/dice 或 assets/icons/arrow_token.png。
- 新素材僅做 Lanczos 清晰縮圖最佳化以利單一 ZIP 傳輸，未重畫；原生成完整解析度在先前 20261011 素材 ZIP。
- 12 個骰面由生成的六宮格按固定六格裁切，不是程式重畫，也非原版骰改色。

使用方法：
  1. 解壓縮整包。第一次配置先執行 SET_TOKEN.bat，再執行 START.bat。
  2. 若原本已有 Token：請自己把自己的 .env 移到新資料夾，切勿上傳或分享 Token。
  3. 原版模式仍可開局。老酒館選項現階段僅供檢視素材與未來設定。
  4. 命令提示字元輸入 python TEST_v081_asset_integration.py 可檢查新素材；
     python selftest.py 可以離線跑原版 3～8 人 AI 遊戲。

下一階段分批實作：
  B 酒館骰與新人物 → C 酋長箭 → D 特殊身分（3 秒反應）→ E 鬼魂 2 骰玩法。
完成全部規則與多人回歸測試後才開啟擴充模組開局。

官方英文規則：
https://www.dvgiochi.com/giochi/OldSaloon/download/BANG%21DiceGame_OldSaloon_Rules_ENG.pdf
