# Terraform configuration to deploy the Skynet Agent Builder on Google Cloud

terraform {
  required_version = ">= 1.0.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  type        = string
  description = "The Google Cloud Project ID"
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "The Google Cloud region to deploy resources to"
}

# 1. Enable Required APIs
resource "google_project_service" "services" {
  for_each = toset([
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "aiplatform.googleapis.com",
  ])
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# 2. Secret Manager for API Keys
resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "gemini-api-key"
  project   = var.project_id
  replication {
    auto {}
  }
  depends_on = [google_project_service.services]
}

# 3. Cloud Run Service hosting the Flask server
resource "google_cloud_run_v2_service" "skynet_server" {
  name     = "skynet-agent-builder"
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/skynet/server:latest"

      env {
        name  = "GCP_LOCATION"
        value = var.region
      }

      # Inject API key securely from Secret Manager
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }
    }
  }

  depends_on = [google_project_service.services]
}

# 4. IAM binding to allow public access to Cloud Run service
resource "google_cloud_run_v2_service_iam_member" "noauth" {
  project    = var.project_id
  location   = google_cloud_run_v2_service.skynet_server.location
  name       = google_cloud_run_v2_service.skynet_server.name
  role       = "roles/run.invoker"
  member     = "allUsers"
  depends_on = [google_cloud_run_v2_service.skynet_server]
}
