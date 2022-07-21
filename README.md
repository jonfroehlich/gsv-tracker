# gsv-capture-dates
In this project, we aim to analyze patterns in Google Street View data collection and examine spatio-temporal patterns such as:
- What areas of the world are most frequently updated and why might this be (look at density patterns, socio-economics, etc.)
- What areas of the world have been most recently updated

## Running the notebook locally using Anaconda 
To setup your dev environment, follow the instructions below. We use [Anaconda](https://www.anaconda.com/) for environment management. If you're unfamiliar, please consult the [Managing Environments](https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html) section in the conda docs for more details. There is also a nice conda cheetsheet [here](https://docs.conda.io/projects/conda/en/4.6.0/_downloads/52a95608c49671267e40c689e0bc00ca/conda-cheatsheet.pdf).

### Step 1: Open your Anaconda terminal and go to the src dir
On **Mac**, this should be as simple as opening `terminal` (or [`iterm2`](https://iterm2.com/)). On **Windows**, open the `Anaconda Powershell Prompt`.

Make sure you are in the root directory of this project. For example, for me (on my Windows), this is:

```
> pwd
D:\git\gsv-capture-dates
```

### Step 2: Create an environment from the environment.yml file

```
> conda env create -f environment.yml
```

This might take a few mins but should end with something like

```
done
#
# To activate this environment, use
#
#     $ conda activate gsv-date-analysis
#
# To deactivate an active environment, use
#
#     $ conda deactivate
```

Optionally, if you'd like to list the active conda environments on your system and verify that the `gsv-date-analysis` environment was created:

```
> conda env list
```

### Step 3: Activate the environment

```
> conda activate gsv-date-analysis
```

### Step 4: Open jupyter notebook
Now you should see the command line prompt prefixed by the current environment: `(gsv-date-analysis)`. So, your command prompt should look like the following or something similar:

```
(gsv-date-analysis)$
```

Now you can type in `jupyter notebook` and find `analysis.ipynb`. 

```
(gsv-date-analysis)$ jupyter notebook
```

In Jupyter Notebook environment, navigate to the `analysis.ipynb` file and open it.

