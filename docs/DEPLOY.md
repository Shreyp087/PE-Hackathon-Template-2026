# Deployment Guide

This guide details the procedure for deploying the URL Shortener service to DigitalOcean.

## 1. Provision a Server
- Go to your DigitalOcean Control Panel.
- **Create a Droplet**:
  - Image: Ubuntu 22.04 LTS.
  - Size: Basic plan, Regular Intel/AMD with at least 1GB RAM (2GB recommended to safely handle both the database and the monitoring stack).
  - Add your SSH keys.
- Once provisioned, log into your new Droplet via SSH:
  ```bash
  ssh root@<DROPLET_IP_ADDRESS>
  ```

## 2. Install Docker & Docker Compose
Run the following script to systematically install Docker and the Docker compose plugin on Ubuntu 22.04:
```bash
# Update packages
apt-get update && apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose plugin
apt-get install docker-compose-plugin -y
```

## 3. Clone the Repository
Pull the application code down to the server:
```bash
git clone https://github.com/YourUsername/PE-Hackathon-Template-2026.git url-shortener
cd url-shortener
```

## 4. Set Up Environment Variables
Create a `.env` file based on the provided example layout:
```bash
cp .env.example .env
nano .env
```
_Ensure you secure your system by changing default passwords and setting `FLASK_DEBUG=false`._

## 5. Deploy the Application
Bring up the application, Database, and monitoring stack globally in detached mode:
```bash
docker compose up -d
```

## 6. Verify Deployment
Check if the applications are running up effectively and hit the API health check:
```bash
# Verify the state of the containers
docker ps -a

# Check API Health locally inside the Droplet
curl -sS http://localhost:5000/health
```

## Rollback Procedure
If a new deployment breaks the application severely, utilize this rollback procedure to revert the traffic to an earlier, stable image.

1. Find the known safe image ID or explicitly versioned tag (e.g., `<image_id>` or `v1.0.0`):
```bash
docker images
```
2. Re-tag the old working image to the tag referenced directly in your `docker-compose.yml` (e.g., `latest` or URL parameter):
```bash
docker tag <working_image_id> your-app-image:latest
```
3. Purge the crashing containers and spin up the fallback containers utilizing the tag you just enforced:
```bash
docker compose down
docker compose up -d
```
