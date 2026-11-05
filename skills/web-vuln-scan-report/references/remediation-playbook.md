# 修复方案代码库（报告第 12 章素材）

每条修复意见必须给出「最小可执行变更 + 验收方式」，禁止停留在"加强鉴权"。以下片段按发现类型组织，写报告时挑相关条目并替换为目标的真实路径/域名。

## 鉴权类（未授权可达接口）

```java
// Spring Security 6 / Boot 3.x（Boot 2.x 用 antMatchers）
http.authorizeHttpRequests(auth -> auth
        .requestMatchers("/auth/login", "/common/config/data").permitAll()
        .requestMatchers("/common/file/upload", "/id/card/face/check").authenticated()
        .anyRequest().authenticated())
    .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS));
```

必须匿名上传时改预签名直传（Controller 不收文件体）：

```java
String uploadUrl = minioClient.getPresignedObjectUrl(
    GetPresignedObjectUrlArgs.builder().method(Method.PUT)   // 只授 PUT
        .bucket("zmka-upload").object(key)                   // key 服务端生成，含用户/业务绑定
        .expiry(5, TimeUnit.MINUTES).build());
```

## 对象存储匿名读（MinIO）

```bash
mc alias set prod https://<minio-host> <AK> <SK>
mc anonymous set none prod/zmka      # 旧版 mc 为 mc policy set none
mc anonymous get  prod/zmka          # 复核应返回 none
mc ls --recursive prod/zmka          # 盘点历史对象（证件照/申报材料→按数据泄露处置）
```

```java
// 公开分发对象改短期签名 URL（≤10 分钟）
String url = minioClient.getPresignedObjectUrl(
    GetPresignedObjectUrlArgs.builder().method(Method.GET)
        .bucket("zmka").object(key).expiry(10, TimeUnit.MINUTES).build());
```

nginx 应急止血（桶策略改造前）：

```nginx
location ^~ /zmka/ { deny all; }
```

## nginx 加固

```nginx
server_tokens off;
```

## Spring Boot 错误页

```yaml
server:
  error:
    include-message: never
    include-stacktrace: never
    whitelabel:
      enabled: false   # 需自备 ErrorController 或 nginx 兜底，避免空响应
```

## CORS 收敛

```java
@Bean
CorsConfigurationSource corsConfigurationSource() {
    CorsConfiguration c = new CorsConfiguration();
    c.setAllowedOrigins(List.of("https://<site-domain>"));
    c.setAllowedMethods(List.of("GET", "POST", "PUT", "DELETE"));
    c.setAllowedHeaders(List.of("Authorization", "Content-Type", "token", "lang")); // 按前端实际用头，漏配会 403
    c.setAllowCredentials(true);
    c.setMaxAge(3600L);
    UrlBasedCorsConfigurationSource s = new UrlBasedCorsConfigurationSource();
    s.registerCorsConfiguration("/**", c);
    return s;
}
```

## SockJS / STOMP

```java
// ① 传输层来源收敛（替换默认 *:*）
registry.addEndpoint("/socket")
        .setAllowedOriginPatterns("https://<site-domain>")
        .withSockJS();

// ② 应用层：CONNECT 校验 token，SUBSCRIBE 校验目的地归属（比 Origin 更先修）
@Component
public class AuthChannelInterceptor implements ChannelInterceptor {
    @Override
    public Message<?> preSend(Message<?> msg, MessageChannel ch) {
        StompHeaderAccessor acc = MessageHeaderAccessor.getAccessor(msg, StompHeaderAccessor.class);
        if (acc != null && StompCommand.CONNECT.equals(acc.getCommand())) {
            verifyToken(acc.getFirstNativeHeader("token"));
        }
        if (acc != null && StompCommand.SUBSCRIBE.equals(acc.getCommand())) {
            verifyDestinationOwner(acc.getDestination(), currentUser());
        }
        return msg;
    }
}
```

## 会话令牌 Cookie 加固

```
Set-Cookie: <token-name>=<jwt>; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=7200
```

```js
// 前端：删除 js-cookie 写入；axios 打开 withCredentials
axios.create({ baseURL: "/dev-sys-api", withCredentials: true, timeout: 10000 })
```

小程序端折衷：HttpOnly refresh cookie + 短期 access token 存内存。

## 全局异常映射（替代非标准状态码）

```java
@RestControllerAdvice
public class GlobalExceptionHandler {
    @ExceptionHandler(Exception.class)
    public ResponseEntity<?> unknown(Exception e) {
        String traceId = UUID.randomUUID().toString();
        log.error("unhandled error traceId={}", traceId, e);
        return ResponseEntity.status(500).body(Map.of("code", 500, "msg", "系统繁忙", "traceId", traceId));
    }
}
```

## 瓦片/静态资源去裸 IP

```nginx
location /gis-tiles/ {
    proxy_pass http://tiles.internal:10861/bfdt/;   # 占位，按实际上游替换
    proxy_cache_valid 200 30d;
    add_header Cache-Control "public, max-age=2592000";
}
```

## 依赖升级

```bash
npm install axios@^1.20.0 && npm run build
# 回归点：自定义请求头（token/lang）、multipart 上传、静默错误处理、超时
```

生命周期类（Vue 2.7 EOL 等）写"短期封版监控 + 长期迁移立项"，不承诺小版本补丁——生态停更没有补丁可打。
