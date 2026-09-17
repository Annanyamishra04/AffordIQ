# AffordIQ 💰

### AI-Powered Financial Affordability & Purchase Decision Platform

> **Can I safely afford this — and if not, what would make it safe?**

🔗 **Live Demo:** https://afford-iq.vercel.app/
---

## 📌 About AffordIQ

**AffordIQ** is a full-stack financial decision-support application that helps users understand whether they can safely afford a purchase.

Instead of checking only the current bank balance, AffordIQ looks at the user's overall financial situation, including:

* Current balance
* Regular income
* Recurring expenses
* Essential spending
* Upcoming payments
* Payment options
* Future cash flow

Based on this information, the application provides a clear recommendation:

**BUY NOW · BUY WITH PLAN · WAIT · DON'T PROCEED**

I built AffordIQ to work on a real-world problem while combining **financial forecasting, intelligent decision-making, backend development, APIs, and a modern React frontend**.

---

## ✨ Features

### 💳 Purchase Affordability

Enter the item, price, currency, and when the payment is needed.

AffordIQ analyzes the user's financial situation and determines whether the purchase is affordable.

### 📈 90-Day Financial Forecast

The system projects the user's cash flow for the next 90 days by considering:

* Income
* Recurring expenses
* Essential spending
* Upcoming commitments
* Planned payments

This helps the application avoid making a decision based only on today's balance.

### 💰 Payment Plan

If paying the full amount immediately is not suitable, AffordIQ checks available payment options and can suggest a safer payment plan.

### 🔄 What-If Analysis

Users can experiment with scenarios such as:

> "What if I stop my gym membership?"

or

> "What if I reduce some flexible spending?"

The application recalculates the financial situation and shows how the decision changes.

### 📅 Financial Timeline

A visual 90-day timeline helps users understand upcoming income, expenses, commitments, and projected balance.

### 🧠 Decision Explanation

AffordIQ doesn't just return a result.

It also shows the important factors behind the decision so the user can understand **why** the purchase is considered safe or unsafe.

### 👤 Demo Profiles

The project includes fictional demo users with synthetic financial data, so the application can be tested without using real financial information.

### 🕘 Decision History

Previous purchase decisions can be viewed from the History section during the current application session.

---

## 🖥️ UI Design

I designed AffordIQ as a **Financial Control Room** rather than a traditional dashboard.

The interface includes:

* Central affordability gauge
* Financial signal strip
* 90-day financial timeline
* Payment-plan timeline
* What-If scenario analysis
* Decision explanation
* Profile section
* Decision history
* Responsive design

The frontend uses **React + Vite + custom CSS**, with custom SVG visualizations for the financial gauge and timeline.

---

## 🏗️ How It Works

```text
User enters purchase
        ↓
Financial profile & transactions
        ↓
Income / expense analysis
        ↓
90-day cash-flow forecast
        ↓
Safety check
        ↓
Payment-plan analysis
        ↓
Optional What-If analysis
        ↓
Final purchase decision
```

The frontend is responsible for the user interface, while the actual financial calculations and decision-making are handled by the Python backend.

---

## 🛠️ Tech Stack

### Frontend

* React
* Vite
* JavaScript
* CSS
* SVG

### Backend

* Python
* Flask
* Flask-CORS
* Gunicorn

### Testing

* pytest

### Data

* CSV
* Synthetic financial data

### AI / Intelligent Decision Support

AffordIQ does not require a paid AI API or API key at runtime.

The financial intelligence is implemented using:

* Financial calculations
* Cash-flow forecasting
* Date-based analysis
* Recurring transaction detection
* Payment-plan analysis
* What-If scenario analysis
* Rule-based financial evidence extraction

This makes the project lightweight and easy to run and deploy without an external AI API key.

---

## 🔌 API Endpoints

| Method | Endpoint                  | Description                |
| ------ | ------------------------- | -------------------------- |
| GET    | `/api/health`             | Check backend status       |
| GET    | `/api/users`              | Get demo users             |
| GET    | `/api/profile/<user_id>`  | Get financial profile      |
| GET    | `/api/forecast/<user_id>` | Get 90-day forecast        |
| POST   | `/api/decision`           | Generate purchase decision |
| POST   | `/api/what-if`            | Test a financial scenario  |
| GET    | `/api/history`            | View decision history      |
| GET    | `/api/history/<id>`       | View a specific decision   |

---

## 🚀 Run Locally

### 1. Clone the repository

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd affordiq
```

### 2. Install backend dependencies

```bash
python -m venv .venv
```

For Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Then install the dependencies:

```bash
pip install -r backend/requirements.txt
```

### 3. Start the backend

```bash
python backend/api.py
```

Backend:

```text
http://127.0.0.1:5001
```

### 4. Start the frontend

Open another terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend:

```text
http://127.0.0.1:5173
```

---

## ☁️ Deployment

AffordIQ can be deployed using free-tier hosting.

```text
GitHub
   │
   ├── Frontend → Vercel / Netlify
   │
   └── Backend  → Render
```

The frontend connects to the deployed backend using:

```text
VITE_API_BASE_URL
```

### 🌐 Live Demo

**Live Link:** `PASTE_YOUR_LIVE_LINK_HERE`

After deployment, replace the placeholder above with your actual live frontend URL.

---

## 🧪 Testing

Run the test suite with:

```bash
python -m pytest tests/ -v
```

The tests cover important parts of the application, including:

* Affordability calculations
* Minimum balance protection
* Recurring income and expenses
* Upcoming payments
* Payment plans
* What-If scenarios
* Message parsing
* Image evidence handling
* Currency conversion
* Financial forecasting
* API validation

All test data is synthetic.

---

## 📊 Example

Suppose a user wants to buy a laptop for **₹60,000**.

AffordIQ does not simply check:

```text
Current Balance > ₹60,000
```

Instead, it considers the user's upcoming financial situation:

```text
Current Balance
      +
Expected Income
      -
Recurring Expenses
      -
Essential Spending
      -
Upcoming Payments
      ↓
90-Day Financial Forecast
      ↓
Affordability Analysis
      ↓
Purchase Decision
```

The application can then determine whether the purchase can be made now, should be paid through a plan, should be delayed, or should not be made under the current financial situation.

---

## 🎯 What I Learned

While building AffordIQ, I worked on:

* Full-stack application development
* React frontend development
* Flask REST APIs
* Financial data processing
* Cash-flow forecasting
* Decision-making logic
* What-If scenario analysis
* API integration
* Automated testing
* Responsive UI development
* Deployment preparation
* Handling real-world edge cases

---

## ⚠️ Limitations

AffordIQ is a **portfolio/demo project** and is not a banking application or professional financial-advisory service.

Current limitations include:

* Uses synthetic demo data
* Decision history is stored in memory
* No direct bank-account integration
* Forecast quality depends on the provided financial data
* Message parsing supports a limited set of patterns

---

## 🔮 Future Improvements

Some features I would like to add in future versions:

* SQLite/database-backed history
* More natural-language financial input
* More language support
* Expense comparison
* Financial report export
* Saved What-If scenarios
* Optional bank integrations
* More personalized financial insights

---

## 👩‍💻 About

**AffordIQ** is a personal portfolio project focused on combining:

**Financial Forecasting + Intelligent Decision Support + Full-Stack Development**

I wanted to build a project around a practical real-world problem instead of creating another basic CRUD or expense-tracking application.

---


---

## 📄 Disclaimer

AffordIQ is created for educational and demonstration purposes only.

It is **not financial advice** and should not be used as a replacement for professional financial guidance.

The demo application uses fictional/synthetic financial data.
