# 📝 Roadmap: Agentic MCP Engine

## Fase 1: Infraestructura como Código y Contenedores
- [ ] **Dockerfiles:** crear imágenes separadas y optimizadas para el Gateway (FastAPI), el Worker (Python) y el Servidor MCP.
- [ ] **docker-compose.yml:** orquestar los 3 microservicios junto a PostgreSQL (con pgvector) y RabbitMQ en una red privada.
- [ ] **Test de despliegue:** levantar todo desde cero con `docker compose up --build` y validar la comunicación entre servicios.

## Fase 2: Blindaje Perimetral (Zero-Trust MCP)
- [ ] **Autenticación server-side:** middleware en el puerto 8080 (MCP) que rechace toda petición sin un Bearer Token criptográfico válido.
- [ ] **Validación estricta (Pydantic):** límites duros de negocio en los argumentos de las herramientas. Por ejemplo, rechazar reembolsos mayores a $5000 en la interfaz, pida lo que pida el LLM.
- [ ] **Rate limiting:** cuota de peticiones aislada por endpoint, contra drenaje de fondos y DoS.

## Fase 3: RAG con AWS Bedrock
> Requisito para poder poner "RAG" en el CV.
- [ ] **Habilitar pgvector:** activar la extensión en PostgreSQL mediante una migración de Alembic.
- [ ] **Módulo de embeddings:** script con `boto3` que vectorice los documentos de negocio (PDFs de políticas de garantía y reembolsos) usando Amazon Titan Embeddings y los inserte en pgvector.
- [ ] **Inyección de contexto dinámico:** modificar el Worker para que haga una búsqueda por similitud coseno antes de llamar a Claude vía Bedrock e inyecte la política relevante en el prompt de sistema.

## Fase 4: Chaos Engineering y Stress Testing (Armagedón)
- [ ] **Configurar Locust:** crear `locustfile.py` y el entorno de pruebas de carga.
- [ ] **Simulación de ataque:** 100+ peticiones concurrentes (usuarios reclamando a la vez) para estresar el Gateway y la cola.
- [ ] **Validación de concurrencia:** comprobar que los bloqueos pesimistas (`SELECT ... FOR UPDATE`) aguantan sin deadlocks.
- [ ] **Métricas:** documentar throughput (req/s) y latencia P95 en el README principal.

## Fase 5: Migración a Cloud (AWS Serverless)
> Objetivo: costo ~$5/mes o $0 en free tier.
- [ ] **IAM y Bedrock:** credenciales y políticas IAM de mínimo privilegio para consumir los modelos fundacionales. Sumar VPC endpoints (PrivateLink) para que el tráfico no salga a internet.
- [ ] **Topología serverless:** FastAPI → API Gateway, RabbitMQ → SQS, Worker → Lambda.
- [ ] **Base de datos externa:** PostgreSQL serverless (Neon o Supabase) con pgvector, para mantener ese costo en $0.
- [ ] **Re-test de carga:** repetir la Fase 4 contra el despliegue en AWS y comparar las métricas con las locales.

## Fase 6: Admin Ops Dashboard (Frontend)
> Requisito para validar el perfil Full-Stack E-commerce.
- [ ] **Setup:** proyecto React + Vite con TypeScript y TailwindCSS.
- [ ] **Panel en tiempo real:** tabla que consuma la API y muestre el estado de las transacciones (PENDING, PROCESSING, COMPLETED) vía WebSocket, SSE o polling.
- [ ] **Métricas visuales:** throughput, latencia y tasa de reembolsos aprobados vs rechazados por el modelo.
