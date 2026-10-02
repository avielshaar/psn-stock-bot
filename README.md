# PSN India Gift-Card Stock Bot 🎮

בוט שמנטר גיפט קארדים של PlayStation Store India ב-Amazon.in ושולח התראה לטלגרם ו/או לקבוצת וואטסאפ ברגע שיש מלאי זמין לרכישה.

## איך זה עובד
1. כל ~90 שניות (עם jitter אקראי) הבוט טוען את דף המוצר `amazon.in/dp/<ASIN>` של כל כרטיס.
2. הפרסר מחליט: **במלאי** = יש כפתור Add to Cart/Buy Now וגם אין "Currently unavailable". **אזל** = יש הודעת אי-זמינות ואין כפתור קנייה. **חסימה** = captcha/503/429. **לא מזוהה** = מבנה העמוד השתנה (אף פעם לא גורם להתראה).
3. התראה נשלחת רק אחרי `confirm_checks` קריאות רצופות "במלאי" (ברירת מחדל 2), פעם אחת לכל "הופעת מלאי". היא נפתחת מחדש אחרי 2 קריאות "אזל".
4. אם שליחה נכשלת בכל הערוצים – ינסה שוב בסבב הבא. המצב נשמר ב-`data/state.json` (אין התראות כפולות אחרי restart).
5. חסימה מצד Amazon → האטה אקספוננציאלית (עד 30 דקות) + הודעת מנהל. עמוד שלא מפוענח 8 פעמים ברצף → הודעת מנהל.

## התקנה
```bash
cd psn-stock-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # ואז למלא (ראה למטה)
python -m pytest -q      # 25 בדיקות
```

### טלגרם (5 דקות)
1. ב-Telegram דבר עם `@BotFather` → `/newbot` → העתק את הטוקן ל-`TELEGRAM_BOT_TOKEN`.
2. שלח לבוט `/start` (או הוסף אותו לקבוצה וכתוב בה הודעה).
3. `python -m psnbot telegram-chat-id` → יציג את ה-chat id (קבוצות מתחילות ב-`-100`) → ל-`TELEGRAM_CHAT_IDS`.

### וואטסאפ (דרך green-api.com)
אין API רשמי חינמי לקבוצות, אז משתמשים בשירות Green API (יש תוכנית Developer חינמית, מוגבלת למספר צ'אטים).
1. הרשמה ב-green-api.com, יצירת instance, סריקת QR עם וואטסאפ של **מספר ייעודי** (מומלץ לא המספר האישי הראשי – שירות לא רשמי, יש סיכון תיאורטי לחסימה).
2. העתק `idInstance` ו-`apiTokenInstance` ל-`.env`. אם בקונסולה מופיע apiUrl אחר – שים ב-`GREENAPI_API_URL`.
3. הוסף את המספר הייעודי לקבוצה, ואז `python -m psnbot greenapi-groups` → ה-id של הקבוצה (`...@g.us`) → ל-`GREENAPI_CHAT_IDS`.

### בדיקות לפני הפעלה
```bash
python -m psnbot verify   # מציג כותרת אמיתית של כל מוצר ובודק שהיא תואמת לסכום
```
```bash
python -m psnbot test-notify        # הודעת בדיקה לכל הערוצים
python -m psnbot check B07K6RYVHR   # טוען דף אמיתי ומדפיס מה הפרסר הבין
python -m psnbot once               # סבב אחד
python -m psnbot run                # ניטור רציף
```

### הפעלה 24/7
`docker compose up -d --build` (שרת/VPS/Raspberry Pi/NAS), או `nohup python -m psnbot run &`, או שירות systemd.

## מוצרים
ב-`config.yaml`. נמצאו (₹1000, ₹2000, ₹3000, ₹4000, ₹7000). ₹500 ו-₹5000 לא אותרו – הדבק את ה-ASIN מכתובת הדף. אפשר `max_price` להתראה רק מתחת למחיר מסוים.
הכרטיסים מיועדים לחשבון PSN הודי (גיל 18+).

## מגבלות חשובות (לקרוא!)
- **לא נבדק מול Amazon.in חי.** בסביבה שבה נבנה הבוט אין גישה לאתר. הפרסר נבדק מול דפי דוגמה שנכתבו לפי המבנה הידוע של Amazon (`#availability`, `#add-to-cart-button`, `#outOfStock` וכו'). לפני שסומכים עליו הרץ `python -m psnbot check <ASIN>` על דף במלאי ועל דף שאזל; אם התוצאה `unknown` – שלח לי את ה-HTML ואתאים.
- אם `check` מחזיר `blocked` (captcha): הבוט משתמש כברירת מחדל ב-`curl_cffi` שמחקה את החיבור של Chrome ומבקר קודם בדף הבית. אם עדיין חסום: `python -m psnbot check ASIN --save page.html` ושלח לי את הפלט, או נעבור לדפדפן אמיתי (Playwright) / proxy.
- Amazon חוסמת סקריפטים, בעיקר מ-IP של שרתי ענן. הכי יציב: מחשב/Raspberry ביתי, או proxy ב-`config.yaml`. אל תוריד את ה-interval מתחת ל~60 שניות.
- סקרייפינג של Amazon מנוגד לתנאי השימוש שלהם; מיועד לשימוש אישי בקצב נמוך.
- מוכרים צד-ג' משנים מחיר/זמינות מהר; ההתראה מציגה מחיר ומוכר כדי שתוכל להחליט.

## מבנה
```
psnbot/amazon.py     שליפה + פענוח מלאי     psnbot/monitor.py    לוגיקת התראות/חסימות
psnbot/notifiers.py  טלגרם / Green API / webhook   psnbot/state.py  שמירת מצב
psnbot/config.py     הגדרות + .env          tests/               25 בדיקות כולל e2e מול שרתי mock
```
