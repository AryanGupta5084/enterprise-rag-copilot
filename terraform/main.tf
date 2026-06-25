provider "aws" {
  region = "us-east-1"
}

variable "db_password" {
  type        = string
  description = "The password for the PostgreSQL master user"
  sensitive   = true
}

variable "vpc_id" {
  type        = string
  description = "The target VPC ID where the infrastructure will be deployed"
  default     = "vpc-xxxxxxxx"
}

resource "aws_security_group" "app_sg" {
  name        = "enterprise-rag-app-sg"
  description = "Security group for ECS Fargate tasks"
  vpc_id      = var.vpc_id

  ingress {
    description = "FastAPI Port"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Streamlit UI Port"
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

# Qdrant Vector DB Security Group
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
  subnet_id              = "subnet-xxxxxx"

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

resource "aws_secretsmanager_secret" "copilot_secrets" {
  name        = "enterprise-rag-api-secrets"
  description = "API keys for Tavily, Upstash, and Google/OpenAI"
}

# --- COMPUTE & ORCHESTRATION LAYER (ECS FARGATE) ---

resource "aws_ecs_cluster" "rag_cluster" {
  name = "enterprise-rag-copilot-cluster"
}

resource "aws_ecs_task_definition" "rag_task" {
  family                   = "rag-copilot-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024" 
  memory                   = "2048" 
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn # Assumed IAM executor setup exists

  container_definitions = jsonencode([
    {
      name      = "rag-copilot-api"
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
        { 
          name  = "DB_URI", 
          value = "postgresql://postgres:${var.db_password}@${aws_db_instance.postgres_checkpointer.endpoint}/postgres" 
        },
        {
          name  = "S3_CORPUS_BUCKET",
          value = aws_s3_bucket.raw_corpus_bucket.id
        },
        {
          name  = "QDRANT_URL",
          value = "http://${aws_instance.qdrant_node.private_ip}:6333"
        }
      ]
      secrets = [
        { name = "TAVILY_API_KEY", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:TAVILY_API_KEY::" },
        { name = "UPSTASH_REDIS_HOST", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:UPSTASH_REDIS_HOST::" },
        { name = "UPSTASH_REDIS_PASSWORD", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:UPSTASH_REDIS_PASSWORD::" },
        { name = "GOOGLE_API_KEY", valueFrom = "${aws_secretsmanager_secret.copilot_secrets.arn}:GOOGLE_API_KEY::" }
      ]
    },
    
    {
      name      = "rag-copilot-ui"
      image     = "your-aws-account-id.dkr.ecr.us-east-1.amazonaws.com/rag-copilot:latest"
      essential = true
      command   = ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
      portMappings = [
        {
          containerPort = 8501
          hostPort      = 8501
          protocol      = "tcp"
        }
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