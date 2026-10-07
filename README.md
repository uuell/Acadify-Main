# Acadify Backend

Acadify is an academic grading and classroom management system designed to help students, teachers, and administrators manage academic records, classes, assessments, grading, and AI-assisted paper checking.

This repository contains the **Flask backend API** for Acadify. The frontend is being developed separately using React and TypeScript.

## Tech Stack

### Backend

- Python
- Flask
- Flask-SQLAlchemy
- Flask-Migrate
- Flask-Login
- Flask-Bcrypt
- Flask-CORS

### Database

- SQLite for local development
- PostgreSQL for production

### Deployment

- GitHub for source control
- Render for backend hosting and production PostgreSQL

## Main Features

Acadify supports multiple user roles:

### Students

- Student authentication
- View enrolled classes
- View grades and academic results
- Access student-specific academic information

### Teachers

- Teacher authentication
- Create and manage classes
- Manage subjects and class schedules
- Enroll students
- Create assessments and tests
- Configure grading formulas
- Record student scores
- Calculate term grades
- Calculate student class averages
- Manage grading completion

### Administrators

- Administrator authentication
- Manage users
- Create students and teachers
- Bulk-import student and teacher records using CSV files
- Manage Acadify system data

### AI-Assisted Grading

Acadify includes an OCR-assisted grading workflow that can process uploaded test papers, extract student and score information, and assist teachers during the grading process.

## Project Structure

```text
acadify-backend/
├── blueprints/
│   ├── admin/
│   ├── auth/
│   ├── ocr/
│   ├── student/
│   └── teacher/
├── migrations/
├── app.py
├── config.py
├── extensions.py
├── requirements.txt
├── build.sh
├── README.md
└── .gitignore
```

The exact structure may change as Acadify continues development.

## Local Development

### 1. Clone the repository

```bash
git clone <repository-url>
cd acadify-backend
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

### 3. Activate the virtual environment

Windows:

```bash
venv\Scripts\activate
```

macOS/Linux:

```bash
source venv/bin/activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure environment variables

Create a `.env` file for development environment variables and secrets.

The `.env` file is excluded from Git and must not be committed to the repository.

### 6. Apply database migrations

```bash
flask db upgrade
```

### 7. Run the Flask application

```bash
flask run
```

## Database Migrations

Acadify uses Flask-Migrate and Alembic for database schema migrations.

When models are changed, create a migration with:

```bash
flask db migrate -m "Describe migration"
```

Apply migrations with:

```bash
flask db upgrade
```

The `migrations/` directory should be committed to Git because production deployments use these migration files to update the PostgreSQL database.

## API Architecture

The backend is organized using Flask Blueprints.

Main API areas include:

```text
/auth
/student
/teacher
/admin
/ocr
```

A health endpoint is also available for verifying that the backend is running.

```text
GET /api/health
```

## Authentication

Acadify uses session-based authentication with Flask-Login.

The React frontend communicates with the Flask backend using credentials-enabled requests.

Example:

```typescript
fetch(url, {
  credentials: "include",
});
```

Authentication currently uses browser session cookies rather than JWT tokens.

## Development and Production Databases

Acadify uses different database configurations depending on the environment.

Development:

```text
SQLite
```

Production:

```text
PostgreSQL
```

Local database files such as `.db`, `.sqlite`, and `.sqlite3` are excluded from Git.

## Deployment

The backend is designed to be deployed using Render.

The Render build process uses:

```bash
./build.sh
```

The build script:

1. Installs Python dependencies from `requirements.txt`.
2. Applies database migrations using Flask-Migrate.

Production secrets and database credentials must be configured using environment variables and must never be committed to GitHub.

## Security

The following files and directories are intentionally excluded from source control:

```text
.env
.env.local
.env.production
venv/
instance/
*.db
*.sqlite
*.sqlite3
```

Never commit secret keys, database passwords, API keys, or other sensitive credentials.

## Current Status

Acadify is currently under active development.

The Flask backend is being migrated from a traditional Flask/Jinja application into a JSON API architecture for use with a React + TypeScript frontend.