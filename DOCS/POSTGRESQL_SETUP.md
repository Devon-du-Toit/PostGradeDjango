## Database Setup

PostGrade uses PostgreSQL as its database backend.

### DB Requirements

- PostgreSQL 17
- pgAdmin 4
- Python 3.13
- Django
- Psycopg 3
- python-dotenv

### 1. Install PostgreSQL

Install PostgreSQL 17 and pgAdmin 4.

During installation, configure the PostgreSQL server and remember the password for the default `postgres` administrator account.

For the current development environment, PostgreSQL is running on:

```
Host: localhost
Port: 5433
```


### 2. Create a PostgreSQL User

Using pgAdmin 4:

Expand the PostgreSQL server.
Right-click Login/Group Roles.
Select Create -> Login/Group Role.
Create the following user:

```
Name: postgrade_user
Can login: Yes
Superuser: No
Create roles: No
Create databases: Yes
```

```
N.B Production: The production PostGrade database user should not be given
the CREATEDB permission. This permission is only required for the local
development/testing setup.
```

Set a password for the user.

Do not use the PostgreSQL postgres superuser as the application's database user.

### 3. Create the PostGrade Database

In pgAdmin 4:

Right-click Databases.
Select Create -> Database.
Configure:

```
Database: postgrade
Owner: postgrade_user
```

Django will create and manage the database tables through migrations. Tables should not be created manually in pgAdmin.

### 4. Install the PostgreSQL Python Driver

Activate the project virtual environment and install Psycopg and pythong-dotenv:

```
python -m pip install "psycopg[binary]" python-dotenv
```

### 5. Create the Environment File

Create a .env file in the project root, alongside manage.py.

Example:

```
DB_NAME=postgrade
DB_USER=postgrade_user
DB_PASSWORD=your-local-database-password
DB_HOST=localhost
DB_PORT=5433
```

### 6. Create and Apply Migrations

Create migrations:

```
python manage.py makemigrations
```

```
python manage.py migrate
```