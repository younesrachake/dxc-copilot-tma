{{- define "dxc-copilot.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "dxc-copilot.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "dxc-copilot.labels" -}}
app.kubernetes.io/name: {{ include "dxc-copilot.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "dxc-copilot.backend.fullname" -}}
{{ include "dxc-copilot.fullname" . }}-backend
{{- end -}}

{{- define "dxc-copilot.frontend.fullname" -}}
{{ include "dxc-copilot.fullname" . }}-frontend
{{- end -}}
