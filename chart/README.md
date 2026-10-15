# ha-enoceanmqtt

Helmchart for ha-enoceanmqtt

**Homepage:** <https://github.com/ChristopheHD/HA_enoceanmqtt>

## Values

This document provides detailed configuration options for the Home Assistant Helm chart.

| Parameter | Description | Default |
| --------- | ----------- | ------- |
| `namespaceOverride` | Override the namespace | `.Release.Namespace` |
| `image.repository` | Repository for the image | |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `image.tag` | Overrides the image tag (default is the chart appVersion) | `""` |
| `image.imagePullSecrets` | List of imagePullSecrets for private image repositories | `[]` |
| `nameOverride` | Override the default name of the Helm chart | `""` |
| `fullnameOverride` | Override the default full name of the Helm chart | `""` |
| `serviceAccount.create` | Specifies whether a service account should be created | `true` |
| `serviceAccount.annotations` | Annotations to add to the service account | `{}` |
| `serviceAccount.name` | The name of the service account to use | `""` |
| `podAnnotations` | Annotations to add to the pod | `{}` |
| `deploymentAnnotations` | Annotations to add to the Deployment | `{}` |
| `securityContext` | Container security context settings | `{}` |
| `podSecurityContext` | Pod security context settings | `{}` |
| `env` | Environment variables | `[]` |
| `envFrom` | Use environment variables from ConfigMaps or Secrets | `[]` |
| `resources` | Resource settings for the container | `{}` |
| `nodeSelector` | Node selector settings for scheduling the pod on specific nodes | `{}` |
| `tolerations` | Tolerations settings for scheduling the pod based on node taints | `[]` |
| `affinity` | Affinity settings for controlling pod scheduling | `{}` |
| `priorityClassName` | Priority class name for pods | `""` |
| `networkPolicy.cilium.egress` | Cilium network policy egress https://docs.cilium.io/en/stable/security/policy/ | `[]` |
| `networkPolicy.cilium.ingress` | Cilium network policy ingress https://docs.cilium.io/en/stable/security/policy/ | `[]` |
| `networkPolicy.egress`  | Kubernetes egress spec https://kubernetes.io/docs/concepts/services-networking/network-policies/ | `[]` |
| `networkPolicy.enabled` | Enable network policy management | `false` |
| `networkPolicy.flavor` | Network policy mode in kubernetes, cilium | `kubernetes` |
| `networkPolicy.ingress`  | Kubernetes ingress spec https://kubernetes.io/docs/concepts/services-networking/network-policies/| `[]` |
| `persistence.enabled` | Enables the creation of a Persistent Volume Claim (PVC) | `false` |
| `persistence.accessMode` | The access mode of the PVC. | `ReadWriteOnce` |
| `persistence.size` | The size of the PVC to create. | `5Gi` |
| `persistence.storageClass` | The storage class to use for the PVC. If empty, the default storage class is used. | `""` |
| `persistence.existingVolume` | The name of an existing Persistent Volume to bind to when using StatefulSet. This bypasses dynamic provisioning. | `""` |
| `persistence.existingClaim` | The name of an existing PVC to use when using Deployment. | `""` |
| `persistence.matchLabels` | Label selectors to apply when binding to an existing Persistent Volume. | `{}` |
| `persistence.matchExpressions` | Expression selectors to apply when binding to an existing Persistent Volume. | `{}` |
| `persistence.annotations` | Annotations to add to the PVC. | `{}` |
| `extraVolumes` | Additional volumes to be mounted in the container | `[]` |
| `extraVolumeMounts` | Additional volume mounts to be mounted in the container | `[]` |
| `configMount` | Mount spec for config, allow override | `[]` |
| `initContainers` | List of initialization containers | `[]` |
| `enoceanmqtt` | Software configuration bloc, see values for details | `{}` |
