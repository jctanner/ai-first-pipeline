package main

import (
	"crypto/tls"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
)

// Route configuration
type Route struct {
	Host    string
	Backend string
}

var routes = []Route{
	{
		Host:    "github-emulator.ai-pipeline.svc.cluster.local",
		Backend: "https://github-emulator.ai-pipeline.svc.cluster.local:443",
	},
	{
		Host:    "github.local",
		Backend: "https://github-emulator.ai-pipeline.svc.cluster.local:443",
	},
	{
		Host:    "jira-emulator.ai-pipeline.svc.cluster.local",
		Backend: "https://jira-emulator.ai-pipeline.svc.cluster.local:443",
	},
	{
		Host:    "jira.local",
		Backend: "https://jira-emulator.ai-pipeline.svc.cluster.local:443",
	},
	{
		Host:    "dashboard.ai-pipeline.svc.cluster.local",
		Backend: "http://pipeline-dashboard.ai-pipeline.svc.cluster.local:5000",
	},
	{
		Host:    "dashboard.local",
		Backend: "http://pipeline-dashboard.ai-pipeline.svc.cluster.local:5000",
	},
	{
		Host:    "mlflow.ai-pipeline.svc.cluster.local",
		Backend: "http://mlflow.ai-pipeline.svc.cluster.local:5000",
	},
	{
		Host:    "mlflow.local",
		Backend: "http://mlflow.ai-pipeline.svc.cluster.local:5000",
	},
	{
		Host:    "markovd.ai-pipeline.svc.cluster.local",
		Backend: "http://markovd.ai-pipeline.svc.cluster.local:8080",
	},
	{
		Host:    "markovd.local",
		Backend: "http://markovd.ai-pipeline.svc.cluster.local:8080",
	},
}

func getBackend(host string) string {
	// Strip port from host if present
	if idx := strings.Index(host, ":"); idx != -1 {
		host = host[:idx]
	}

	for _, route := range routes {
		if strings.EqualFold(route.Host, host) {
			return route.Backend
		}
	}
	return ""
}

func proxyHandler(w http.ResponseWriter, r *http.Request) {
	backend := getBackend(r.Host)
	if backend == "" {
		log.Printf("No backend found for host: %s", r.Host)
		http.Error(w, "404 Not Found", http.StatusNotFound)
		return
	}

	backendURL, err := url.Parse(backend)
	if err != nil {
		log.Printf("Failed to parse backend URL %s: %v", backend, err)
		http.Error(w, "500 Internal Server Error", http.StatusInternalServerError)
		return
	}

	proxy := httputil.NewSingleHostReverseProxy(backendURL)

	// Configure transport to skip TLS verification for internal CA certs
	proxy.Transport = &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
	}

	// Customize director to set proper headers
	originalDirector := proxy.Director
	proxy.Director = func(req *http.Request) {
		originalDirector(req)
		// Save original host for X-Forwarded-Host
		req.Header.Set("X-Forwarded-Host", r.Host)
		req.Header.Set("X-Forwarded-Proto", r.URL.Scheme)
		if r.TLS != nil {
			req.Header.Set("X-Forwarded-Proto", "https")
		}
		// Override Host header to match backend service DNS name
		// Caddy is configured to match on the full service DNS name
		req.Host = backendURL.Hostname()
	}

	// Log the request
	log.Printf("%s %s -> %s%s", r.Method, r.Host, backend, r.URL.Path)

	proxy.ServeHTTP(w, r)
}

func main() {
	// HTTP handler
	http.HandleFunc("/", proxyHandler)

	// Start HTTP server
	go func() {
		log.Println("Starting HTTP server on :80")
		if err := http.ListenAndServe(":80", nil); err != nil {
			log.Fatalf("HTTP server failed: %v", err)
		}
	}()

	// Start HTTPS server
	certFile := os.Getenv("TLS_CERT_FILE")
	keyFile := os.Getenv("TLS_KEY_FILE")

	if certFile == "" {
		certFile = "/etc/tls/tls.crt"
	}
	if keyFile == "" {
		keyFile = "/etc/tls/tls.key"
	}

	// Load multiple certificates for different hosts
	tlsConfig := &tls.Config{
		MinVersion: tls.VersionTLS12,
	}

	// Try to load cert files
	if _, err := os.Stat(certFile); err == nil {
		log.Printf("Starting HTTPS server on :443 with cert: %s", certFile)
		server := &http.Server{
			Addr:      ":443",
			Handler:   http.DefaultServeMux,
			TLSConfig: tlsConfig,
		}

		if err := server.ListenAndServeTLS(certFile, keyFile); err != nil {
			log.Fatalf("HTTPS server failed: %v", err)
		}
	} else {
		log.Printf("TLS cert not found, running HTTP only")
		select {} // Block forever
	}
}
