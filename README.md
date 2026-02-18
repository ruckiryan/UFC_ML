# UFC Fight Outcome Prediction (Machine Learning Project)

This project uses logistic regression (Binary Classification) and ML to predict each fighers (red/blue corner) probability of winning based on fighter attributes, statistics, and historical performance.

Currently, three UFC events (UFC322, UFCQatar, UFC324) have been trained and predicted. To view the model's result's on these previous events please checkout the model's [outcomes](/OUTCOMES.md).

# Getting Started:

> [!NOTE]
> The following section of this README assumes that the development environment has access (and uses) standard UNIX tools like [`bash/zsh`](https://www.gnu.org/software/bash/) and [`git`](https://git-scm.com/). Please make sure you have them installed before continuing.
> Windows users: It is recommended to either use `git bash` or the [Windows Subsystem For Linux](https://learn.microsoft.com/en-us/windows/wsl/install)

## Cloning the repository:

In whatever directory you store programming-related projects, run:

```sh
# HTTP:
$ git clonehttps://github.com/ruckiryan/UFC_ML.git

# SSH:
$ git@github.com:ruckiryan/UFC_ML.git

# Navigate to the project directory:
$ cd UFC_ML
```

Then, open the project using your favorite text editor.

## Creating a virtual enviornment:

For this section you will need to have `Python 3.12` (we are using the latest 3.12 version [3.12.12], but any 3.12.x should work) installed and as the working interpreter of the project. We recommend [pyenv](https://github.com/pyenv/pyenv).

1. Ensure you have the correct python version:

```sh
$ python --version

# If the shell does not return:
$ Python 3.12.x

# Run:
$ pyenv local 3.12.12

# Check version again:
$ python --version
$ python 3.12.12
```

2. Make and activate the virtual env:

```sh
$ python -m venv .venv
$ source .venv/bin/activate
```

## Installing Project Dependencies:

The project currently has 2 different `requirements.txt` files. The first [`requirements.txt`](/requirements.txt) installs the core runtime dependencies to train the model and perform data analytics. The other [`requirements-dev.txt`](/requirements-dev.txt), contains additional packages for running and editing jupyter notebooks, doing interactive plotting, and other miscellaneous packages. **For simply running the model, it is recommended that you install the basic `requirements.txt`**:

```sh
$ pip install -r requirements.txt
```

## Training a model

**TODO IN PROGRESS, UPDATE AS NEEDED**

```sh
$ cd src
$ python model_fillename.py # train the actual model.
$ predict.py # predict the event.
```
