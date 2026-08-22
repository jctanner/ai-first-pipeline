package main

import (
	"crypto/tls"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"
)

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
		Host:    "fullsend-dashboard.ai-pipeline.svc.cluster.local",
		Backend: "http://fullsend-dashboard.ai-pipeline.svc.cluster.local:5000",
	},
	{
		Host:    "fullsend.local",
		Backend: "http://fullsend-dashboard.ai-pipeline.svc.cluster.local:5000",
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
	{
		Host:    "observatory.ai-pipeline.svc.cluster.local",
		Backend: "http://observatory.ai-pipeline.svc.cluster.local:8000",
	},
	{
		Host:    "observatory.local",
		Backend: "http://observatory.ai-pipeline.svc.cluster.local:8000",
	},
	{
		Host:    "gitlab-emulator.ai-pipeline.svc.cluster.local",
		Backend: "https://gitlab-emulator.ai-pipeline.svc.cluster.local:443",
	},
	{
		Host:    "gitlab.local",
		Backend: "https://gitlab-emulator.ai-pipeline.svc.cluster.local:443",
	},
}

var (
	proxyCache      map[string]*httputil.ReverseProxy
	hostToBackend   map[string]string
	sharedTransport *http.Transport
	initOnce        sync.Once
)

func initProxies() {
	sharedTransport = &http.Transport{
		TLSClientConfig:       &tls.Config{InsecureSkipVerify: true},
		DialContext:           (&net.Dialer{Timeout: 5 * time.Second}).DialContext,
		ResponseHeaderTimeout: 120 * time.Second,
		MaxIdleConns:          100,
		MaxIdleConnsPerHost:   10,
		IdleConnTimeout:       90 * time.Second,
	}

	proxyCache = make(map[string]*httputil.ReverseProxy)
	hostToBackend = make(map[string]string)

	for _, route := range routes {
		host := strings.ToLower(route.Host)
		hostToBackend[host] = route.Backend

		if _, exists := proxyCache[route.Backend]; exists {
			continue
		}

		backendURL, err := url.Parse(route.Backend)
		if err != nil {
			log.Fatalf("Failed to parse backend URL %s: %v", route.Backend, err)
		}

		proxy := httputil.NewSingleHostReverseProxy(backendURL)
		proxy.Transport = sharedTransport
		proxy.ErrorHandler = func(w http.ResponseWriter, req *http.Request, err error) {
			log.Printf("proxy error: %s -> %s: %v", req.Header.Get("X-Forwarded-Host"), req.URL.Host, err)
			http.Error(w, "502 Bad Gateway", http.StatusBadGateway)
		}

		proxyCache[route.Backend] = proxy
	}

	log.Printf("Initialized %d cached reverse proxies for %d routes", len(proxyCache), len(routes))
}

func getBackend(host string) string {
	if idx := strings.Index(host, ":"); idx != -1 {
		host = host[:idx]
	}
	return hostToBackend[strings.ToLower(host)]
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	w.Write([]byte("ok"))
}

func proxyHandler(w http.ResponseWriter, r *http.Request) {
	backend := getBackend(r.Host)
	if backend == "" {
		log.Printf("No backend found for host: %s", r.Host)
		http.Error(w, "404 Not Found", http.StatusNotFound)
		return
	}

	proxy, ok := proxyCache[backend]
	if !ok {
		log.Printf("No cached proxy for backend: %s", backend)
		http.Error(w, "500 Internal Server Error", http.StatusInternalServerError)
		return
	}

	backendURL, _ := url.Parse(backend)

	originalDirector := proxy.Director
	director := func(req *http.Request) {
		originalDirector(req)
		req.Header.Set("X-Forwarded-Host", r.Host)
		req.Header.Set("X-Forwarded-Proto", "http")
		if r.TLS != nil {
			req.Header.Set("X-Forwarded-Proto", "https")
		}
		req.Host = backendURL.Hostname()
	}

	wrapped := *proxy
	wrapped.Director = director

	log.Printf("%s %s -> %s%s", r.Method, r.Host, backend, r.URL.Path)

	wrapped.ServeHTTP(w, r)
}

func main() {
	initOnce.Do(initProxies)

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", healthHandler)
	mux.HandleFunc("/", proxyHandler)

	go func() {
		server := &http.Server{
			Addr:         ":80",
			Handler:      mux,
			ReadTimeout:  30 * time.Second,
			WriteTimeout: 120 * time.Second,
			IdleTimeout:  60 * time.Second,
		}
		log.Println("Starting HTTP server on :80")
		if err := server.ListenAndServe(); err != nil {
			log.Fatalf("HTTP server failed: %v", err)
		}
	}()

	certFile := os.Getenv("TLS_CERT_FILE")
	keyFile := os.Getenv("TLS_KEY_FILE")

	if certFile == "" {
		certFile = "/etc/tls/tls.crt"
	}
	if keyFile == "" {
		keyFile = "/etc/tls/tls.key"
	}

	tlsConfig := &tls.Config{
		MinVersion: tls.VersionTLS12,
	}

	if _, err := os.Stat(certFile); err == nil {
		log.Printf("Starting HTTPS server on :443 with cert: %s", certFile)
		server := &http.Server{
			Addr:         ":443",
			Handler:      mux,
			TLSConfig:    tlsConfig,
			ReadTimeout:  30 * time.Second,
			WriteTimeout: 120 * time.Second,
			IdleTimeout:  60 * time.Second,
		}

		if err := server.ListenAndServeTLS(certFile, keyFile); err != nil {
			log.Fatalf("HTTPS server failed: %v", err)
		}
	} else {
		log.Printf("TLS cert not found, running HTTP only")
		select {}
	}
}
