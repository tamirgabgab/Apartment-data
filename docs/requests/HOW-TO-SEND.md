# How to send the two data requests

Step-by-step guide for the owner. The letters themselves are ready in Hebrew:

| # | Letter | To | Channel | Cost | Answer expected |
|---|---|---|---|---|---|
| 1 | [`permission-nadlan.md`](permission-nadlan.md) | Survey of Israel (מרכז למיפוי ישראל), operator of nadlan.gov.il | Email `nadlan@mapi.gov.il` (or the site's contact form) | Free | No legal deadline |
| 2 | [`foi-tax-authority.md`](foi-tax-authority.md) | FOI officer of the Israel Tax Authority (הממונה על חוק חופש המידע, רשות המסים) | The gov.il online form for Freedom of Information requests | A small request fee, sometimes also production fees | 30 days by law, can be extended |

Send both. They do not depend on each other, and either one is enough to unblock Phase 3.

---

## Before you start (5 minutes)

1. Open both letter files and replace every `[...]` field:
   - `[שם מלא]`, `[כתובת דואר אלקטרוני]`, `[טלפון]`, `[תאריך]` in both letters.
   - `[ת"ז]` (ID number) only in the FOI letter. Do not put it in the email to the Survey of Israel.
2. Use an email address you read often. Answers can take weeks, and missing one can close the request.
3. Copy only the Hebrew text, from **"לכבוד"** to the signature. Do not copy the English lines above the `---`.
4. Do not commit the filled-in letters with your ID number or phone number to the repository, because it is public. Keep a filled copy on your computer.

---

## Request 1: permission from the Survey of Israel

### Option A: email (recommended)

Email leaves a written record with a date, and has no length limit.

- **To:** `nadlan@mapi.gov.il` (the address the site itself publishes for inquiries)
- **Subject:**
  ```
  בקשה לאישור שימוש בנתוני עסקאות מאתר הנדל"ן הממשלתי לפרויקט ציבורי לא מסחרי
  ```
- **Body:** the full Hebrew letter from `permission-nadlan.md`, from "לכבוד" to your signature.
- Optional: add a link to the live site, which shows that the project is real and non-commercial:
  ```
  האתר הקיים, המבוסס כיום על נתוני הלמ"ס ובנק ישראל: https://apartment-data.vercel.app
  ```

### Option B: the contact form on the site

1. Go to https://www.nadlan.gov.il
2. Scroll to the page footer and click **"יצירת קשר"**.
3. Fill in the full name (שם מלא), email (מייל) and any other required fields.
4. Paste the letter into the message field. If the field is too short, write one line that says you are sending a formal request by email, and use option A.
5. Take a screenshot of the confirmation.

### What to expect

- There is no legal deadline. If nothing arrives within **3–4 weeks**, send a short polite reminder that replies to your first email.
- Possible answers: approval with conditions (an API key, a data file or terms of use), a referral to the Tax Authority, or a refusal. In every case, send me the answer and I will update the plan.

---

## Request 2: Freedom of Information request to the Tax Authority

### Where to submit

Government ministries and authorities take Freedom of Information requests through a central online form on gov.il.

1. Go to https://www.gov.il and search for **"בקשה לקבלת מידע לפי חוק חופש המידע"**.
2. Open the online form (הגשת בקשה מקוונת). It usually needs identification (הזדהות) with the government login or with your ID number.
3. Choose the authority **רשות המסים בישראל** from the list.

> I could not open gov.il from the development environment, so the exact screen names may differ slightly. If you cannot find the form, search for "חופש המידע רשות המסים" and use the link on the Tax Authority's own page.

### What to fill in

- **Personal details:** name, ID number, address, email and phone.
- **Subject (נושא הבקשה):**
  ```
  נתוני עסקאות מכר במקרקעין למגורים מ-2000 ואילך (ללא פרטים מזהים)
  ```
- **Request text (פירוט המידע המבוקש):** the full Hebrew letter from `foi-tax-authority.md`. If the field is limited, paste sections 1–5 and attach the full letter as a PDF or Word file, if the form allows attachments.
- **Delivery format:** electronic, CSV or Excel files.

### Fees

- There is a **request fee** (אגרת בקשה), usually a few tens of shekels, paid by credit card in the form. The exact amount appears on the form.
- If producing the data takes many work hours, the authority may ask for an extra **processing / production fee** (אגרת טיפול והפקה) and tell you the amount before it starts. You can then agree, ask for a smaller scope (the letter already offers "cities only" or "from 2010"), or decline.

### Deadlines (by the Freedom of Information Law)

- The authority must answer within **30 days**.
- It can extend this by another 30 days, and in some cases further, but it has to tell you so in writing.
- Note the date you sent the request and the request number (מספר פנייה) the system gives you.

### Possible answers and what to do

| Answer | What to do |
|---|---|
| Full approval, with a file or a link | Send it to me. Raw files go to private Supabase Storage, not to GitHub. |
| Partial approval (some fields removed) | Fine for the website. Send it to me. |
| A fee demand | Tell me the amount, and we decide together or narrow the scope. |
| Refusal | Send me the reasons. The law allows a narrower new request, or an appeal to court (an administrative petition), and a narrower request is usually enough. |
| No answer after 30 days | Send a reminder through the same system or by email, quoting the request number. |

---

## After sending

Tell me in the next session, and I will record it in `HANDOFF.md` (Phase 3 and the open questions). This table is a record of what was sent:

| Request | Sent on | Channel | Reference number | Remind on | Status |
|---|---|---|---|---|---|
| 1. Survey of Israel | | | | (+3 weeks) | |
| 2. Tax Authority FOI | | | | (+30 days) | |
