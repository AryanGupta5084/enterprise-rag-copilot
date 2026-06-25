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

resource "aws_security_group" "alb_sg" {
  name        = "enterprise-rag-alb-sg"
  description = "Allow public HTTPS traffic to ALB"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTPS from anywhere"
    from_port   = 443
    to_port     = 443
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

# --- NEW: LOAD BALANCER & NETWORKING ---

resource "aws_lb" "rag_alb" {
  name               = "enterprise-rag-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = ["subnet-xxxxxx", "subnet-yyyyyy"]
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

data "aws_acm_certificate" "api_cert" {
  domain   = "api.yourdomain.com"
  statuses = ["ISSUED"]
}

# HTTPS Listener
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.rag_alb.arn
  port              = "443"
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-2016-08"
  certificate_arn   = data.aws_acm_certificate.api_cert.arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.rag_api_tg.arn
  }
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
    assign_public_ip = false
    security_groups  = [aws_security_group.app_sg.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.rag_api_tg.arn
    container_name   = "rag-copilot-api"
    container_port   = 8000
  }
}