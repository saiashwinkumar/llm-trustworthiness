# Run Qwen3-8B on an AWS GPU and use it from VS Code

Your laptop runs data preparation, experiment requests, and analysis. An AWS EC2 instance runs the model. An SSH tunnel connects them. You do not need a GPU on your laptop.

This guide describes setup steps for you to perform; no AWS resources have been created for you. Complete the local installation in `README.md` first. The project uses a small Transformers + FastAPI server because the experiment needs model scores, not only generated chat responses.

## 1. Check the AWS account and choose a region

1. Sign in to the [AWS console](https://console.aws.amazon.com/). Use an account with permission to create EC2 instances and view Service Quotas.
2. Select one region in the top-right corner. Keep that region selected throughout setup. Choose a region offering the instance below; a region near you reduces request latency.
3. Open **Service Quotas → AWS services → Amazon Elastic Compute Cloud (Amazon EC2)**.
4. Search for **Running On-Demand G and VT instances**. This quota counts vCPUs, not GPUs. For one `g6.2xlarge` or `g5.2xlarge`, you need at least **8 available vCPUs** in that quota. If the applied value is too small, request an increase. A quota increase does not guarantee spare hardware capacity. [AWS quota documentation](https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-quotas.html).
5. Check the On-Demand price shown for your chosen region and instance before launch. Include EBS disk storage and public IPv4 charges when estimating the total. You can use the [AWS Pricing Calculator](https://calculator.aws/). A billing budget alert can help track spending, but it does not automatically stop an instance.

Start with On-Demand rather than Spot so an interruption does not complicate your first experiment.

## 2. Launch one GPU instance

Open **EC2 → Instances → Launch instances**. Use the following settings:

| Setting | Selection |
|---|---|
| Name | `choice-trust-qwen` |
| Instance type | **`g6.2xlarge`**: one NVIDIA L4 GPU with 24 GB, 8 vCPUs, 32 GiB system RAM |
| Alternative | **`g5.2xlarge`**: one NVIDIA A10G GPU with 24 GB, 8 vCPUs, 32 GiB system RAM |
| AMI | Current **AWS Deep Learning OSS NVIDIA Driver AMI GPU PyTorch**, **Ubuntu**, **x86_64** |
| Storage | **100 GiB gp3 EBS** root volume; encrypt it |
| Key pair | Create a key pair named `choice-trust-key`; download the `.pem` file |
| Network | Public subnet with internet access; enable auto-assigned public IPv4 |
| Inbound security group | **SSH/TCP 22 → My IP** only |
| Outbound security group | Leave default outbound access enabled for package/model downloads |

Choose the full `g6.2xlarge`, not a `g6f` fractional GPU instance. You do not need a multi-GPU machine for this starter project. AWS lists the [G6 specifications](https://aws.amazon.com/ec2/instance-types/g6/) and [G5 specifications](https://aws.amazon.com/ec2/instance-types/g5/).

In the AMI picker, select an **Amazon-published** GPU PyTorch image. Do not select a CPU, ARM64, Inferentia, or Trainium image. Consult the [current DLAMI release list](https://docs.aws.amazon.com/dlami/latest/devguide/appendix-ami-release-notes.html) to choose a maintained release rather than an old tutorial's AMI ID. When this guide was prepared, the supported list included **GPU PyTorch 2.13 on Ubuntu 26.04**, with [this AWS setup page](https://docs.aws.amazon.com/dlami/latest/devguide/aws-deep-learning-x86-gpu-pytorch-2.13-ubuntu-26-04.html). AMI IDs and names vary by region and release.

Do not add an inbound rule for port 8000. The model server listens only on the instance's own loopback address, and you reach it through SSH. AWS documents [restricting SSH access to your computer's public IP](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/security-group-rules-reference.html).

Click **Launch instance** after reviewing the selected configuration and price. Wait for the instance status checks to pass. Copy its **Public IPv4 address**, for example `203.0.113.10`. The example address in this guide is a placeholder; substitute your actual address.

## 3. Connect from your laptop

Keep your key outside the project folder. Never put it in Git or share it. The following examples assume you saved it under your home directory's `.ssh` folder.

### macOS or Linux terminal in VS Code

Move the downloaded key into `~/.ssh/choice-trust-key.pem` using your file manager, then run:

```bash
chmod 400 ~/.ssh/choice-trust-key.pem
ssh -i ~/.ssh/choice-trust-key.pem ubuntu@YOUR_PUBLIC_IP
```

### Windows PowerShell terminal in VS Code

Use the built-in OpenSSH client. Replace the key path with your actual path:

```powershell
ssh -i "$env:USERPROFILE\.ssh\choice-trust-key.pem" ubuntu@YOUR_PUBLIC_IP
```

If SSH reports that the key file permissions are too open, follow AWS's [private-key permission instructions](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/connection-prereqs-general.html) for Windows. In File Explorer, right-click the key, choose **Properties → Security → Advanced**, disable inheritance, and remove access for accounts other than your own.

Use **`ubuntu`** for the Ubuntu AMI. If you deliberately chose Amazon Linux 2023 instead, its default username is **`ec2-user`**, and you must substitute that username in every command. [AWS default username reference](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/managing-users.html).

After connecting, the terminal prompt belongs to the remote AWS computer. Commands below marked **AWS terminal** run there. Commands marked **local terminal** run on your laptop.

## 4. Verify the GPU and activate the preinstalled environment

In the **AWS terminal**:

```bash
nvidia-smi
source /opt/pytorch/bin/activate
python --version
which python
python -c "import torch; print('PyTorch:', torch.__version__); print('CUDA:', torch.version.cuda); print('GPU available:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none'); print('BF16 supported:', torch.cuda.is_bf16_supported())"
```

Expected results:

- `nvidia-smi` lists an L4 or A10G GPU.
- `which python` points inside the PyTorch environment.
- `GPU available` and `BF16 supported` are `True`.

The current AWS GPU PyTorch DLAMI documents `source /opt/pytorch/bin/activate`. If your selected maintained image uses a different environment path, check its welcome message and release notes. You can inspect `/opt` with `ls /opt`; use the documented PyTorch environment. Avoid reinstalling the NVIDIA driver or replacing GPU PyTorch with a generic CPU installation.

The local analysis environment can use Python 3.11 or 3.12. On AWS, use the selected DLAMI's compatible, preinstalled Python/PyTorch environment. Record its actual versions rather than trying to change the system Python.

## 5. Copy the model server to AWS

In the **AWS terminal**, create a project folder:

```bash
mkdir -p ~/customer-choice-trust
```

Open a second **local terminal** in VS Code. Change to the downloaded `customer-choice-trust` project folder. Copy only the server and its dependency list:

### macOS or Linux

```bash
scp -i ~/.ssh/choice-trust-key.pem server.py requirements-server.txt ubuntu@YOUR_PUBLIC_IP:~/customer-choice-trust/
```

### Windows PowerShell

```powershell
scp -i "$env:USERPROFILE\.ssh\choice-trust-key.pem" server.py requirements-server.txt ubuntu@YOUR_PUBLIC_IP:~/customer-choice-trust/
```

Back in the **AWS terminal**:

```bash
cd ~/customer-choice-trust
source /opt/pytorch/bin/activate
python -m pip install -r requirements-server.txt
python -m pip check
python -c "import torch, transformers; print('torch:', torch.__version__); print('transformers:', transformers.__version__); assert torch.cuda.is_available()"
python -m pip freeze > server-environment-lock.txt
```

The provided server dependency list intentionally omits `torch` so it can use the GPU build supplied by the DLAMI. Qwen3 requires **Transformers 4.51.0 or newer**; older releases do not recognise its architecture. The project keeps compatible major-version bounds in the requirements file. Keep `server-environment-lock.txt` with the experiment records so the exact resolved package versions can be reproduced.

The instance needs outbound internet access to download packages from PyPI and the model from Hugging Face and its download/CDN infrastructure. The first model download is substantial. The model is public, so a Hugging Face token is normally unnecessary. [Qwen3-8B model card and loading instructions](https://huggingface.co/Qwen/Qwen3-8B).

## 6. Start the model server

In the **AWS terminal**:

```bash
cd ~/customer-choice-trust
source /opt/pytorch/bin/activate
export MODEL_ID=Qwen/Qwen3-8B
export MODEL_REVISION=main
export HF_HOME="$HOME/hf-cache"
read -rsp "Paste the MODEL_API_KEY from your local .env file: " MODEL_API_KEY
printf '\n'
export MODEL_API_KEY
python -m uvicorn server:app --host 127.0.0.1 --port 8000 --workers 1
```

Follow `README.md` to generate the local `.env` key before this step. This key protects your research server; it is not an OpenAI API key and does not require an OpenAI account. Paste the same key into the prompt above. It will not be echoed to the terminal.

The first start downloads and loads Qwen3-8B. Leave this terminal open and wait until startup finishes. The model uses the GPU in BF16 precision. An 8B model's weights use roughly 16 GB at two bytes per parameter; additional memory is needed for inference. The 24 GB recommendation assumes short prompts, one request at a time, and the supplied output limits. It is not a promise that arbitrary context sizes will fit.

Use **one worker**, and leave off `--reload`. Additional workers can each load another model copy and exhaust GPU memory. The project explicitly disables Qwen's thinking mode; the explanation is a separate, short output used in the experiment.

For a formal run, record the model's resolved revision reported by the server. Then replace `MODEL_REVISION=main` with that exact commit hash when restarting future runs, so a later model repository update cannot silently change the experiment.

## 7. Open the private tunnel

Open another **local terminal** in VS Code and leave it open while running the experiment.

### macOS or Linux

```bash
ssh -i ~/.ssh/choice-trust-key.pem -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:8000:127.0.0.1:8000 ubuntu@YOUR_PUBLIC_IP
```

### Windows PowerShell

```powershell
ssh -i "$env:USERPROFILE\.ssh\choice-trust-key.pem" -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:8000:127.0.0.1:8000 ubuntu@YOUR_PUBLIC_IP
```

An apparently idle terminal is normal: it is maintaining the tunnel. Requests sent by your laptop to `http://127.0.0.1:8000` now reach the AWS server through SSH. You should not use the EC2 public IP as the model API URL.

In your local project `.env`, set:

```dotenv
MODEL_BASE_URL=http://127.0.0.1:8000
MODEL_API_KEY=your-existing-long-random-key
```

Keep the actual key you generated during local setup; do not use the placeholder text above. In a **third local terminal**, with the local Python environment activated, test the connection:

```bash
python experiment.py health
```

The response should show `status: ready`, `device: cuda:0`, the model ID, an immutable model revision, and the input/output token limits. `/health` does not require the API key; prediction and explanation endpoints do. Once this works, continue the local smoke run in `README.md`, then the validation and final test runs.

## 8. What to do when something fails

| Symptom | Check |
|---|---|
| Launch says vCPU limit exceeded | Increase **Running On-Demand G and VT instances** in this region to cover 8 vCPUs plus existing usage. |
| Launch says insufficient capacity | Try a different availability zone or the `g5.2xlarge` alternative; quotas and capacity are separate. |
| SSH times out | Check instance status checks, public IPv4, subnet internet route, port 22 rule, and whether **My IP** changed. |
| SSH says permission denied | Check the private key and username. Ubuntu uses `ubuntu`; Amazon Linux uses `ec2-user`. |
| `nvidia-smi` fails | Verify you launched the GPU instance type and an AWS NVIDIA GPU DLAMI. |
| PyTorch says CUDA unavailable | Activate the image's PyTorch environment and confirm `which python`; do not use your laptop's analysis environment. |
| `KeyError: qwen3` | The server environment has an old Transformers version. Reinstall the supplied server requirements in the activated environment. |
| Download fails | Check outbound access and available disk space with `df -h`; model files download on AWS, not through the SSH tunnel. |
| CUDA out of memory | Run only one server worker and one request at a time; stop duplicate model processes and keep the supplied short context/output limits. |
| Local port 8000 is in use | Stop the other local service, or use local port 8001 in the left side of `-L` and change the local API URL accordingly. |
| Local connection refused | Confirm both the remote server and the SSH tunnel are running. |
| HTTP 401/403 | The local and server API keys differ. Restart the server with the matching key. |
| Requests time out during startup | Wait for model loading to finish and check the AWS server terminal. |

## 9. End a session and resume later

1. Stop the local experiment gracefully and check that its output files were written.
2. In the AWS server terminal, press **Ctrl+C** to stop Uvicorn.
3. In the tunnel terminal, press **Ctrl+C**.
4. In the AWS EC2 console, select the instance and choose **Instance state → Stop instance**. Closing VS Code or ending SSH does **not** stop EC2 billing.

When an instance is stopped, instance compute charges stop, but retained **EBS volumes continue to incur storage charges**. Other retained resources, such as Elastic IPs, can also have charges. Files in your Ubuntu home directory on the EBS root volume persist; instance-store disk contents do not. AWS describes [stop/start persistence and costs](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/how-ec2-instance-stop-start-works.html).

To resume, start the instance in the console, copy its current public IP, reconnect, reactivate the environment, start the server with the same key and pinned model revision, and reopen the tunnel. The auto-assigned public IP usually changes after stop/start. Cached model files on EBS should remain available.

When permanently finished, download any AWS-only records you need before terminating the instance. Check the EBS **Delete on termination** setting and remove retained resources you no longer need. Termination permanently removes the instance and any volumes configured for deletion. [AWS termination documentation](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/how-ec2-instance-termination-works.html).

## Official references

- [EC2 G6 instance specifications](https://aws.amazon.com/ec2/instance-types/g6/)
- [EC2 G5 instance specifications](https://aws.amazon.com/ec2/instance-types/g5/)
- [EC2 instance quotas](https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-quotas.html)
- [AWS current Deep Learning AMI release notes](https://docs.aws.amazon.com/dlami/latest/devguide/appendix-ami-release-notes.html)
- [AWS Ubuntu GPU PyTorch DLAMI environment](https://docs.aws.amazon.com/dlami/latest/devguide/aws-deep-learning-x86-gpu-pytorch-2.13-ubuntu-26-04.html)
- [AWS SSH connection prerequisites](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/connect-to-linux-instance.html)
- [AWS instance usernames](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/managing-users.html)
- [Qwen3-8B official model card](https://huggingface.co/Qwen/Qwen3-8B)
- [PyTorch installation reference](https://pytorch.org/get-started/locally/)
- [EC2 stop/start behavior and costs](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/how-ec2-instance-stop-start-works.html)
