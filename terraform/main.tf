terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    upstash = {
      source  = "upstash/upstash"
      version = "~> 1.5"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

provider "upstash" {
  email   = var.upstash_email
  api_key = var.upstash_api_key
}

# --- VARIABLES ---

variable "db_password" {
  type        = string
  description = "The password for the PostgreSQL master user"
  sensitive   = true
}

variable "vpc_id" {
  type        = string
  description = "The target VPC ID where the infrastructure will be deployed"
  default     = "vpc-0ab6ab8cca933cd92"
}

variable "upstash_email" {
  type        = string
  description = "Email associated with your Upstash account"
  sensitive   = true
}

variable "upstash_api_key" {
  type        = string
  description = "Upstash Management API Key"
  sensitive   = true
}

variable "tavily_api_key" {
  type        = string
  description = "Tavily Web Search API Key"
  sensitive   = true
}

variable "google_api_key" {
  type        = string
  description = "Google Gemini API Key"
  sensitive   = true
}

# --- SECURITY GROUPS ---

resource "aws_security_group" "alb_sg" {
  name        = "enterprise-rag-alb-sg"
  description = "Allow public HTTPS traffic to ALB"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress { 
    description = "Streamlit UI from anywhere" 
    from_port   = 8501 
    to_port     = 8501 
    protocol    = "tcp" 
    cidr_blocks = ["0.0.0.0/0"] 
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "app_sg" {
  name        = "enterprise-rag-app-sg"
  description = "Security group for ECS Fargate tasks (Private)"
  vpc_id      = var.vpc_id

  ingress {
    description     = "FastAPI Port via ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  ingress {
    description     = "Streamlit UI Port via ALB"
    from_port       = 8501
    to_port         = 8501
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "db_sg" {
  name        = "enterprise-rag-db-sg"
  description = "Allow DB access strictly from the ECS App Tasks"
  vpc_id      = var.vpc_id

  ingress {
    description     = "PostgreSQL Access"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "qdrant_sg" {
  name        = "enterprise-rag-qdrant-sg"
  description = "Allow Qdrant traffic strictly from the ECS App Tasks"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Qdrant REST API"
    from_port       = 6333
    to_port         = 6333
    protocol        = "tcp"
    security_groups = [aws_security_group.app_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- PERSISTENT DATA STORES ---

resource "aws_db_instance" "postgres_checkpointer" {
  identifier             = "enterprise-rag-postgres"
  engine                 = "postgres"
  engine_version         = "16"
  instance_class         = "db.t4g.micro"
  allocated_storage      = 20
  username               = "postgres"
  password               = var.db_password
  publicly_accessible    = false
  skip_final_snapshot    = true
  vpc_security_group_ids = [aws_security_group.db_sg.id]
}

resource "aws_instance" "qdrant_node" {
  ami           = "ami-0c7217cdde317cfec" 
  instance_type = "t3.medium"          
  
  vpc_security_group_ids = [aws_security_group.qdrant_sg.id]
  subnet_id              = "subnet-073cb7dfafaa62afb"

  root_block_device {
    volume_size           = 50
    volume_type           = "gp3"
    delete_on_termination = true
  }

  user_data = <<-EOF
              #!/bin/bash
              sudo apt-get update -y
              sudo apt-get install -y docker.io
              sudo systemctl start docker
              sudo systemctl enable docker
              
              mkdir -p /opt/qdrant/storage
              
              sudo docker run -d -p 6333:6333 -p 6334:6334 \
                -v /opt/qdrant/storage:/qdrant/storage \
                --name qdrant_server \
                --restart always \
                qdrant/qdrant:latest
              EOF

  tags = {
    Name = "enterprise-rag-qdrant-node"
  }
}

resource "aws_s3_bucket" "raw_corpus_bucket" {
  bucket = "enterprise-rag-raw-corpus-bucket"
}

resource "upstash_redis_database" "rag_cache" {
  database_name = "enterprise-rag-cache"
  region        = "global" 
  primary_region = "us-east-1"
  tls           = true
}

# --- SECRETS MANAGEMENT ---

resource "aws_secretsmanager_secret" "copilot_secrets" {
  name        = "enterprise-rag-api-secrets"
  description = "API keys for Tavily, Upstash, and Google/OpenAI"
}

resource "aws_secretsmanager_secret_version" "copilot_secrets_version" {
  secret_id     = aws_secretsmanager_secret.copilot_secrets.id
  secret_string = jsonencode({
    TAVILY_API_KEY         = var.tavily_api_key
    GOOGLE_API_KEY         = var.google_api_key
    UPSTASH_REDIS_HOST     = upstash_redis_database.rag_cache.endpoint
    UPSTASH_REDIS_PASSWORD = upstash_redis_database.rag_cache.password
    UPSTASH_REDIS_PORT     = upstash_redis_database.rag_cache.port
  })
}

# --- LOAD BALANCER & NETWORKING ---

resource "aws_lb" "rag_alb" {
  name               = "enterprise-rag-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = ["subnet-073cb7dfafaa62afb", "subnet-07dcc2ba4afca0f92"]
}

resource "aws_lb_target_group" "rag_api_tg" {
  name        = "enterprise-rag-api-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/health"
    healthy_threshold   = 3
    unhealthy_threshold = 2
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }
}

resource "aws_lb_listener" "http" { 
  load_balancer_arn = aws_lb.rag_alb.arn 
  port              = "80" 
  protocol          = "HTTP" 
  
  default_action { 
    type             = "forward" 
    target_group_arn = aws_lb_target_group.rag_api_tg.arn 
  } 
}

# --- COMPUTE & ORCHESTRATION LAYER (ECS FARGATE) ---

resource "aws_ecs_cluster" "rag_cluster" {
  name = "enterprise-rag-copilot-cluster"
}

resource "aws_iam_role" "ecs_task_execution_role" {
  name = "enterprise-rag-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_role_policy" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_secrets_policy" {
  name = "enterprise-rag-secrets-policy"
  role = aws_iam_role.ecs_task_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          aws_secretsmanager_secret.copilot_secrets.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "ecs_s3_policy" {
  name = "enterprise-rag-s3-policy"
  role = aws_iam_role.ecs_task_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]

        Resource = [
          aws_s3_bucket.raw_corpus_bucket.arn,
          "${aws_s3_bucket.raw_corpus_bucket.arn}/*"
        ]
      }
    ]
  })
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
      name      = "db-initializer"
      image     = "956380159493.dkr.ecr.us-east-1.amazonaws.com/rag-copilot:latest"
      essential = false
      command   = ["sh", "-c", "python -m src.init_db && python -m src.ingest"]
      environment = [
        { name  = "DB_URI", value = "postgresql://postgres:${var.db_password}@${aws_db_instance.postgres_checkpointer.endpoint}/postgres" },
        { name  = "S3_CORPUS_BUCKET", value = aws_s3_bucket.raw_corpus_bucket.id },
        { name  = "QDRANT_URL", value = "http://${aws_instance.qdrant_node.private_ip}:6333" }
      ]
      secrets = [
        { name = "TAVILY_API_KEY", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:TAVILY_API_KEY::" },
        { name = "UPSTASH_REDIS_HOST", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:UPSTASH_REDIS_HOST::" },
        { name = "UPSTASH_REDIS_PORT", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:UPSTASH_REDIS_PORT::" }, 
        { name = "UPSTASH_REDIS_PASSWORD", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:UPSTASH_REDIS_PASSWORD::" },
        { name = "GOOGLE_API_KEY", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:GOOGLE_API_KEY::" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/enterprise-rag-api"
          "awslogs-region"        = "us-east-1"
          "awslogs-stream-prefix" = "ecs-init"
        }
      }
    },
    {
      name      = "rag-copilot-api"
      image     = "956380159493.dkr.ecr.us-east-1.amazonaws.com/rag-copilot:latest"
      essential = true
      dependsOn = [
        {
          containerName = "db-initializer"
          condition     = "SUCCESS"
        }
      ]
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        { name  = "DB_URI", value = "postgresql://postgres:${var.db_password}@${aws_db_instance.postgres_checkpointer.endpoint}/postgres" },
        { name  = "S3_CORPUS_BUCKET", value = aws_s3_bucket.raw_corpus_bucket.id },
        { name  = "QDRANT_URL", value = "http://${aws_instance.qdrant_node.private_ip}:6333" }
      ]
      secrets = [
        { name = "TAVILY_API_KEY", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:TAVILY_API_KEY::" },
        { name = "UPSTASH_REDIS_HOST", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:UPSTASH_REDIS_HOST::" },
        { name = "UPSTASH_REDIS_PORT", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:UPSTASH_REDIS_PORT::" }, 
        { name = "UPSTASH_REDIS_PASSWORD", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:UPSTASH_REDIS_PASSWORD::" },
        { name = "GOOGLE_API_KEY", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:GOOGLE_API_KEY::" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/enterprise-rag-api"
          "awslogs-region"        = "us-east-1"
          "awslogs-stream-prefix" = "ecs"
        }
      }
    },
    {
      name      = "rag-copilot-ui"
      image     = "956380159493.dkr.ecr.us-east-1.amazonaws.com/rag-copilot:latest"
      essential = true
      dependsOn = [
        {
          containerName = "rag-copilot-api"
          condition     = "START"
        }
      ]
      command   = ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
      portMappings = [
        {
          containerPort = 8501
          hostPort      = 8501
          protocol      = "tcp"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/enterprise-rag-api"
          "awslogs-region"        = "us-east-1"
          "awslogs-stream-prefix" = "ecs-ui"
        }
      }
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
    subnets          = ["subnet-073cb7dfafaa62afb", "subnet-07dcc2ba4afca0f92"] 
    assign_public_ip = true
    security_groups  = [aws_security_group.app_sg.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.rag_api_tg.arn
    container_name   = "rag-copilot-api"
    container_port   = 8000
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.rag_ui_tg.arn
    container_name   = "rag-copilot-ui"
    container_port   = 8501
  }
}

resource "aws_cloudwatch_log_group" "api_logs" {
  name              = "/ecs/enterprise-rag-api"
  retention_in_days = 7
}

resource "aws_lb_target_group" "rag_ui_tg" { 
  name        = "enterprise-rag-ui-tg" 
  port        = 8501 
  protocol    = "HTTP" 
  vpc_id      = var.vpc_id 
  target_type = "ip" 

  health_check { 
    path                = "/healthz"  # Streamlit default health check
    healthy_threshold   = 3 
    unhealthy_threshold = 2 
    timeout             = 5 
    interval            = 30 
    matcher             = "200" 
  } 
}

resource "aws_lb_listener" "ui_http" { 
  load_balancer_arn = aws_lb.rag_alb.arn 
  port              = "8501" 
  protocol          = "HTTP" 

  default_action { 
    type             = "forward" 
    target_group_arn = aws_lb_target_group.rag_ui_tg.arn 
  } 
}