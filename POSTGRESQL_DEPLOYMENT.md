# PostgreSQL Migration and Production Deployment Guide

## Overview

This guide covers the complete migration from SQLite to PostgreSQL and production deployment setup for ChatCode.

## ✅ Migration Completed

The application has been successfully migrated from SQLite to PostgreSQL with the following changes:

### Database Changes
- ✅ Added PostgreSQL dependencies (`psycopg2-binary`, `asyncpg`)
- ✅ Updated database configuration to support both SQLite and PostgreSQL
- ✅ Created migration script (`migrate_to_postgresql.py`)
- ✅ Successfully migrated all existing data
- ✅ Verified database operations work correctly

### Configuration Updates
- ✅ Updated `.env`, `.env.example`, and `.env.production` with PostgreSQL settings
- ✅ Updated `render.yaml` for PostgreSQL deployment
- ✅ Added production-ready PostgreSQL connection settings

## Local Development Setup

### Prerequisites
- PostgreSQL installed and running
- Python 3.8+ with virtual environment

### Setup Steps

1. **Install PostgreSQL** (if not already installed):
   ```bash
   # macOS with Homebrew
   brew install postgresql@14
   brew services start postgresql@14
   
   # Ubuntu/Debian
   sudo apt-get install postgresql postgresql-contrib
   sudo systemctl start postgresql
   ```

2. **Create Database and User**:
   ```bash
   psql postgres -c "CREATE DATABASE chatcode_db;"
   psql postgres -c "CREATE USER chatcode_user WITH PASSWORD 'chatcode_password';"
   psql postgres -c "GRANT ALL PRIVILEGES ON DATABASE chatcode_db TO chatcode_user;"
   psql chatcode_db -c "GRANT ALL ON SCHEMA public TO chatcode_user;"
   ```

3. **Update Environment Variables**:
   ```bash
   # In your .env file
   DB_URL=postgresql://chatcode_user:chatcode_password@localhost:5432/chatcode_db
   ```

4. **Run Migration** (if you have existing SQLite data):
   ```bash
   python migrate_to_postgresql.py
   ```

5. **Start Application**:
   ```bash
   uvicorn app:app --reload
   ```

## Production Deployment

### Render.com Deployment

The application is configured for Render.com with PostgreSQL:

1. **Create PostgreSQL Database**:
   - Go to Render.com dashboard
   - Create a new PostgreSQL database
   - Name: `chatcode-db`
   - Plan: Free (or paid for production)

2. **Deploy Web Service**:
   - Connect your GitHub repository
   - The `render.yaml` file will automatically configure:
     - PostgreSQL database connection
     - Environment variables
     - Build and start commands

3. **Environment Variables**:
   The following variables are automatically configured:
   - `DB_URL`: Connected to PostgreSQL database
   - `APP_SECRET`: Auto-generated secure secret
   - `BASE_URL`: Your production domain
   - OAuth credentials (set manually)

### Other Cloud Providers

#### Heroku
```bash
# Add PostgreSQL addon
heroku addons:create heroku-postgresql:mini

# Set environment variables
heroku config:set APP_SECRET=$(openssl rand -base64 32)
heroku config:set BASE_URL=https://your-app.herokuapp.com
```

#### Railway
```bash
# Add PostgreSQL service
railway add postgresql

# Deploy with environment variables
railway deploy
```

## Database Configuration

### Connection String Format
```
postgresql://username:password@host:port/database_name
```

### Production Settings
The application uses optimized PostgreSQL settings for production:
- Connection pooling (10 connections, 20 overflow)
- Connection pre-ping for reliability
- Connection recycling (300 seconds)
- Proper error handling

## Migration Script Features

The `migrate_to_postgresql.py` script provides:
- ✅ Automatic backup of SQLite database
- ✅ Data validation and verification
- ✅ Error handling and rollback capability
- ✅ Progress reporting
- ✅ Schema compatibility checking

### Running Migration
```bash
# Ensure PostgreSQL is running and configured
python migrate_to_postgresql.py
```

## Verification Steps

### 1. Database Connection Test
```python
python3 -c "
import os
os.environ['DB_URL'] = 'your_postgresql_url'
from app import engine, Session
from sqlmodel import text

with Session(engine) as s:
    result = s.exec(text('SELECT version()')).first()
    print('PostgreSQL version:', result)
"
```

### 2. Data Verification
```bash
# Check user count
psql your_database -c "SELECT COUNT(*) FROM \"user\";"

# Check admin users
psql your_database -c "SELECT username, is_admin FROM \"user\" WHERE is_admin = true;"
```

### 3. Application Test
```bash
# Start application
uvicorn app:app --reload

# Test endpoints
curl http://localhost:8000/
curl -X POST http://localhost:8000/register -d "username=test&password=test123&phone=+12345678901"
```

## Troubleshooting

### Common Issues

1. **Connection Refused**:
   - Ensure PostgreSQL is running
   - Check connection string format
   - Verify database exists

2. **Permission Denied**:
   - Grant proper permissions to database user
   - Check user has access to schema

3. **Migration Errors**:
   - Check SQLite database exists
   - Verify PostgreSQL connection
   - Review migration logs

### Logs and Monitoring

- Application logs: Check uvicorn output
- Database logs: Check PostgreSQL logs
- Connection issues: Enable SQL echo in development

## Security Considerations

### Production Security
- ✅ Use strong database passwords
- ✅ Enable SSL/TLS for database connections
- ✅ Restrict database access by IP
- ✅ Regular security updates
- ✅ Backup and recovery procedures

### Environment Variables
Never commit sensitive data:
- Database passwords
- OAuth secrets
- API keys
- Session secrets

## Backup and Recovery

### Automated Backups
```bash
# Create backup
pg_dump your_database > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore backup
psql your_database < backup_file.sql
```

### Migration Rollback
If needed, the original SQLite database is backed up during migration and can be restored by:
1. Updating `DB_URL` back to SQLite
2. Restoring from backup file
3. Restarting application

## Performance Optimization

### Database Indexes
The application automatically creates indexes for:
- Username (unique)
- Email
- Social ID
- Admin status

### Connection Pooling
Production settings include:
- Pool size: 10 connections
- Max overflow: 20 connections
- Connection recycling: 300 seconds

## Next Steps

1. ✅ Migration completed successfully
2. ✅ Local testing verified
3. 🔄 Deploy to production
4. 🔄 Monitor performance
5. 🔄 Set up automated backups

## Support

For issues or questions:
1. Check application logs
2. Verify database connectivity
3. Review this documentation
4. Check PostgreSQL documentation
