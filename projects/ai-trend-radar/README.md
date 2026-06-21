# AI Trend Radar

A local research tool that collects rising AI projects from GitHub, Hugging Face, and Hacker News, then ranks them as possible video topics.

## What it produces

- `reports/latest.html` — visual dashboard
- `reports/latest.csv` — content-planning table
- `reports/latest.json` — structured results
- `data/radar.db` — snapshots used to measure growth between runs

The first run creates a baseline. Later runs can use changes in stars, likes, downloads, points, and comments as real momentum signals.

## WSL setup — recommended

Keep the project inside the Linux filesystem for better performance rather than working from `/mnt/c`.

Open Ubuntu or your preferred WSL distribution and run:

```bash
cd ~
git clone https://github.com/canukguy1974/colin-builds-ai.git
cd colin-builds-ai/projects/ai-trend-radar
bash setup.sh
bash run.sh
```

The setup script:

- checks for Python and Git
- installs the required Ubuntu packages when necessary
- creates `.venv`
- installs the Python dependency
- creates a private `.env` file
- creates the `data` and `reports` folders

After a successful run, the report should open in your Windows browser. The file is also available at:

```text
reports/latest.html
```

To run it again later:

```bash
cd ~/colin-builds-ai/projects/ai-trend-radar
git pull
bash run.sh
```

## Windows PowerShell setup

Open PowerShell in this folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\run.ps1
```

## Optional GitHub token

Open `.env` and add:

```text
GITHUB_TOKEN=your_token_here
```

Do not commit `.env`. A token is optional, but GitHub allows fewer unauthenticated search requests.

## Configuration

Edit `config.json` to change:

- GitHub searches
- lookback period
- minimum score
- number of displayed projects
- AI keywords
- enabled source behavior

## Scoring

Every project gets 1–5 points for:

1. Momentum
2. Usefulness
3. Visual demonstration potential
4. Accessibility
5. Original-angle opportunity
6. Business or content potential

Maximum score: 30.

This score is a filter, not divine revelation. Review the top candidates before choosing a video.
