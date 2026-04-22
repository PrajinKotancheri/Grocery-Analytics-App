# Publish Grocery Analytics App

This app can be shared publicly with a simple Python host such as Render or Railway.

## Before you deploy

The app now supports host platforms by reading:

- `HOST`
- `PORT`

Locally, it still defaults to `127.0.0.1:8000`.

## Fastest option: Render

1. Put this project in a GitHub repository.
2. Go to https://render.com and sign in.
3. Create a new `Web Service`.
4. Connect your GitHub repository.
5. Render should detect `render.yaml` automatically.
6. Deploy.
7. After the build finishes, Render will give you a public URL like:
   `https://your-app-name.onrender.com`

## Fastest option: Railway

1. Put this project in a GitHub repository.
2. Go to https://railway.app and create a new project.
3. Choose `Deploy from GitHub repo`.
4. Select this repository.
5. Railway will install `requirements.txt` and run:
   `python app.py`
6. Railway will assign a public domain automatically.

## Important note about uploads

This app analyzes PDFs in memory when users upload them. That means:

- you do not need a database for the current version
- uploaded files are not permanently stored
- every user can open the public link and analyze their own PDFs

## If you want custom branding later

You can add:

- a custom domain
- password protection
- login/authentication
- saved analysis history
