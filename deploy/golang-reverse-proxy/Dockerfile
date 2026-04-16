FROM golang:1.22-alpine AS builder

WORKDIR /app

# Copy go mod files
COPY go.mod ./

# Download dependencies
RUN go mod download

# Copy source code
COPY main.go ./

# Build the binary
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o reverse-proxy .

# Final stage - minimal image
FROM alpine:3.19

RUN apk --no-cache add ca-certificates

WORKDIR /app

# Copy the binary from builder
COPY --from=builder /app/reverse-proxy .

# Expose HTTP and HTTPS ports
EXPOSE 80 443

# Run the proxy
CMD ["./reverse-proxy"]
