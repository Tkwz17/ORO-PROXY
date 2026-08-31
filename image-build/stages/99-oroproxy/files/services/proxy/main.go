package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"time"
)

type quotaClient struct {
	baseURL string
	http    *http.Client
}

type quotaRequest struct {
	SessionID string `json:"session_id"`
	ClientMAC string `json:"client_mac"`
}

type quotaResponse struct {
	Allowed bool `json:"allowed"`
}

func (q *quotaClient) allow(ctx context.Context, sessionID, mac string) bool {
	if sessionID == "" || mac == "" {
		return false
	}
	payload, _ := json.Marshal(quotaRequest{SessionID: sessionID, ClientMAC: strings.ToLower(mac)})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, q.baseURL+"/v1/proxy/allow", bytes.NewReader(payload))
	if err != nil {
		return false
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := q.http.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return false
	}
	var out quotaResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return false
	}
	return out.Allowed
}

func main() {
	addr := getenv("OROPROXY_PROXY_ADDR", ":3128")
	quotaURL := getenv("OROPROXY_QUOTA_URL", "http://127.0.0.1:9090")
	server := &proxyServer{quota: &quotaClient{baseURL: quotaURL, http: &http.Client{Timeout: 3 * time.Second}}}
	log.Printf("proxy listening on %s", addr)
	if err := http.ListenAndServe(addr, server); err != nil {
		log.Fatal(err)
	}
}

type proxyServer struct {
	quota *quotaClient
}

func (p *proxyServer) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	sessionID := r.Header.Get("X-OroProxy-Session")
	mac := r.Header.Get("X-Client-MAC")
	if !p.quota.allow(r.Context(), sessionID, mac) {
		http.Error(w, "authentication required", http.StatusProxyAuthRequired)
		return
	}

	if r.Method == http.MethodConnect {
		p.handleConnect(w, r)
		return
	}
	p.handleHTTP(w, r)
}

func (p *proxyServer) handleHTTP(w http.ResponseWriter, r *http.Request) {
	outReq := r.Clone(r.Context())
	outReq.RequestURI = ""
	resp, err := http.DefaultTransport.RoundTrip(outReq)
	if err != nil {
		http.Error(w, "upstream request failed", http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	copyHeader(w.Header(), resp.Header)
	w.WriteHeader(resp.StatusCode)
	_, _ = io.Copy(w, resp.Body)
}

func (p *proxyServer) handleConnect(w http.ResponseWriter, r *http.Request) {
	targetConn, err := net.DialTimeout("tcp", r.Host, 5*time.Second)
	if err != nil {
		http.Error(w, "connect failed", http.StatusBadGateway)
		return
	}
	hj, ok := w.(http.Hijacker)
	if !ok {
		http.Error(w, "hijack unsupported", http.StatusInternalServerError)
		_ = targetConn.Close()
		return
	}
	clientConn, rw, err := hj.Hijack()
	if err != nil {
		_ = targetConn.Close()
		return
	}
	defer clientConn.Close()

	_, _ = rw.WriteString("HTTP/1.1 200 Connection Established\r\n\r\n")
	_ = rw.Flush()

	errCh := make(chan error, 2)
	go pipe(errCh, targetConn, clientConn)
	go pipe(errCh, clientConn, targetConn)
	<-errCh
	_ = targetConn.Close()
}

func pipe(errCh chan<- error, dst io.Writer, src io.Reader) {
	_, err := io.Copy(dst, src)
	if err != nil && !errors.Is(err, net.ErrClosed) {
		errCh <- err
		return
	}
	errCh <- nil
}

func copyHeader(dst, src http.Header) {
	for k, values := range src {
		for _, v := range values {
			dst.Add(k, v)
		}
	}
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func readLine(br *bufio.Reader) (string, error) {
	line, err := br.ReadString('\n')
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(line), nil
}
