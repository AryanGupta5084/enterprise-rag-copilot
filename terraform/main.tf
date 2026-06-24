provider "aws" {
  region = "us-east-1"
}

# 1. PostgreSQL 16 (Amazon RDS for LangGraph Checkpoints)
resource "aws_db_instance" "postgres_checkpointer" {
  identifier             = "enterprise-rag-postgres"
  engine                 = "postgres"
  engine_version         = "16" # Strictly aligns with the diagram
  instance_class         = "db.t4g.micro"
  allocated_storage      = 20
  username               = "postgres"
  password               = var.db_password # Pass securely via terraform apply
  publicly_accessible    = false
  skip_final_snapshot    = true
  vpc_security_group_ids = [aws_security_group.db_sg.id]
}

# 2. S3 Bucket (For Raw PDF Corpus Ingestion)
resource "aws_s3_bucket" "raw_corpus_bucket" {
  bucket = "enterprise-rag-raw-corpus-bucket"
}

# Securely store API Keys (Tavily, Qdrant Cloud, Upstash, LLM)
resource "aws_secretsmanager_secret" "copilot_secrets" {
  name        = "enterprise-rag-api-secrets"
  description = "API keys for Tavily, Upstash, Qdrant, and Google/OpenAI"
}

resource "aws_ecs_cluster" "rag_cluster" {
  name = "enterprise-rag-copilot-cluster"
}

resource "aws_ecs_task_definition" "rag_task" {
  family                   = "rag-copilot-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024" 
  memory                   = "2048" 
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn

  container_definitions = jsonencode([
    {
      name      = "rag-copilot-container"
      image     = "your-aws-account-id.dkr.ecr.us-east-1.amazonaws.com/rag-copilot:latest"
      essential = true
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        # Dynamically inject the newly provisioned RDS Postgres Endpoint
        { 
          name  = "DB_URI", 
          value = "postgresql://postgres:${var.db_password}@${aws_db_instance.postgres_checkpointer.endpoint}/postgres" 
        },
        # Point to the dynamically created S3 Bucket
        {
          name  = "S3_CORPUS_BUCKET",
          value = aws_s3_bucket.raw_corpus_bucket.id
        }
      ]
      # Pull sensitive API keys directly from AWS Secrets Manager
      secrets = [
        { name = "TAVILY_API_KEY", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:TAVILY_API_KEY::" },
        { name = "UPSTASH_REDIS_HOST", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:UPSTASH_REDIS_HOST::" },
        { name = "UPSTASH_REDIS_PASSWORD", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:UPSTASH_REDIS_PASSWORD::" },
        { name = "QDRANT_URL", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:QDRANT_URL::" },
        { name = "QDRANT_API_KEY", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:QDRANT_API_KEY::" },
        { name = "GOOGLE_API_KEY", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:GOOGLE_API_KEY::" }
      ]
    }
  ])
}

resource "aws_ecs_service" "rag_service" {
  name            = "rag-copilot-service"
  cluster         = aws_ecs_cluster.rag_cluster.id
  task_definition = aws_ecs_task_definition.rag_task.arn
  launch_type     = "FARGATE"
  desired_count   = 2

  network_configuration {
    subnets          = ["subnet-xxxxxx", "subnet-yyyyyy"] 
    assign_public_ip = true
    security_groups  = [aws_security_group.app_sg.id]
  }
}