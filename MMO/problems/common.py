import numpy as np
from pymoo.factory import get_from_list, get_reference_directions
from MMO.problems import *
from MMO.external import lhs


def get_problem_options():
    problems = [
        ('zdt1', ZDT1),
        ('zdt2', ZDT2),
        ('zdt3', ZDT3),
        ('dtlz1', DTLZ1),
        ('dtlz2', DTLZ2),
        ('dtlz3', DTLZ3),
        ('dtlz4', DTLZ4),
        ('dtlz5', DTLZ5),
        ('dtlz6', DTLZ6),
        ('oka1', OKA1),
        ('oka2', OKA2),
        ('vlmop2', VLMOP2),
        ('vlmop3', VLMOP3),
        ('re1', RE1),
        ('re2', RE2),
        ('re3', RE3),
        ('re4', RE4),
        ('re5', RE5),
        ('re6', RE6),
        ('re7', RE7),
        ('cdn_ram', CDN_RAM),
        ('cdn_placement', CDN_PLACEMENT)
    ]
    return problems


def get_problem(name, *args, d={}, **kwargs):
    return get_from_list(get_problem_options(), name.lower(), args, {**d, **kwargs})


def generate_initial_samples(problem, n_sample):
    '''
    Generate feasible initial samples.
    Input:
        problem: the optimization problem
        n_sample: number of initial samples
    Output:
        X, Y: initial samples (design parameters, performances)
    '''
    X_feasible = np.zeros((0, problem.n_var))
    Y_feasible = np.zeros((0, problem.n_obj))

    # NOTE: when it's really hard to get feasible samples, the program hangs here
    while len(X_feasible) < n_sample:
        X = lhs(problem.n_var, n_sample)
        X = problem.xl + X * (problem.xu - problem.xl)
        X = np.round(X)
        X_temp = X.copy()
        Y, feasible = problem.evaluate(X, return_values_of=['F', 'feasible'])
        feasible = feasible.flatten()
        X_feasible = np.vstack([X_feasible, X_temp[feasible]])
        Y_feasible = np.vstack([Y_feasible, Y[feasible]])
    indices = np.random.permutation(np.arange(len(X_feasible)))[:n_sample]
    X, Y = X_feasible[indices], Y_feasible[indices]
    return X, Y


def build_problem(name, n_var, n_obj, n_init_sample, n_process=1, extra_params=None, mode=0):
    '''
    Build optimization problem from name, get initial samples
    Input:
        name: name of the problem (supports ZDT1-6, DTLZ1-7)
        n_var: number of design variables
        n_obj: number of objectives
        n_init_sample: number of initial samples
        n_process: number of parallel processes
    Output:
        problem: the optimization problem
        X_init, Y_init: initial samples
        pareto_front: the true pareto front of the problem (if defined, otherwise None)
    '''
    # build problem
    if name.startswith('zdt') or name == 'vlmop2':
        problem = get_problem(name, n_var=n_var)
        pareto_front = problem.pareto_front()
    elif name.startswith('dtlz'):
        problem = get_problem(name, n_var=n_var, n_obj=n_obj)
        if n_obj <= 3 and name in ['dtlz1', 'dtlz2', 'dtlz3', 'dtlz4']:
            ref_kwargs = dict(n_points=100) if n_obj == 2 else dict(n_partitions=15)
            ref_dirs = get_reference_directions('das-dennis', n_dim=n_obj, **ref_kwargs)
            pareto_front = problem.pareto_front(ref_dirs)
        elif n_obj == 3 and name in ['dtlz5', 'dtlz6']:
            pareto_front = problem.pareto_front()
        else:
            pareto_front = None
    else:
        if mode == 0:
            transformToInteger = False
        else:
            transformToInteger = True
        
        if name == "cdn_ram" or name == "cdn_placement":
            problem = get_problem(name, n_var=n_var, n_obj=n_obj, transformToInteger = transformToInteger)
            topo, fileSize, colorMode, colorList, runReqNums, warmUpReqNums, separatorRankIncrement, deleteCachePath, interval = extra_params
            problem.get_parameters(topo, fileSize, colorMode, colorList, runReqNums, warmUpReqNums, separatorRankIncrement, n_process, deleteCachePath, interval)
        else:
            problem = get_problem(name, n_var=n_var, n_obj=n_obj)       
    # get initial samples
    X_init, Y_init = generate_initial_samples(problem, n_init_sample)
    return problem, X_init, Y_init #  problem, pareto_front, X_init, Y_init
